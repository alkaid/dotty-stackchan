import { once } from "node:events";
import { readFile } from "node:fs/promises";
import OpusScript from "opusscript";
import { WebSocketServer } from "ws";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LogStore } from "./log-store.js";

afterEach(() => {
  delete process.env.XIAOZHI_WS_URL;
  delete process.env.XIAOZHI_PUBLIC_WS_BASE_URL;
  delete process.env.XIAOZHI_WS_PORT;
  vi.resetModules();
});

describe("StackChan device protocol", () => {
  it("resolves the published Xiaozhi address for local runs", async () => {
    const { resolveWsUrl } = await import("./device.js");
    expect(resolveWsUrl({
      XIAOZHI_WS_PORT: "5001",
      XIAOZHI_PUBLIC_WS_BASE_URL: "wss://voice.example.test:50001",
    })).toBe("ws://127.0.0.1:5001/xiaozhi/v1/");
    expect(resolveWsUrl({ XIAOZHI_PUBLIC_WS_BASE_URL: "wss://voice.example.test:50001" }))
      .toBe("wss://voice.example.test:50001/xiaozhi/v1/");
    expect(resolveWsUrl({ XIAOZHI_WS_PORT: "5001" }))
      .toBe("ws://127.0.0.1:5001/xiaozhi/v1/");
  });
  it("sends production headers and answers MCP tools/list", async () => {
    const server = new WebSocketServer({ port: 0 });
    await once(server, "listening");
    const address = server.address();
    if (typeof address === "string") throw new Error("unexpected socket address");
    process.env.XIAOZHI_WS_URL = `ws://127.0.0.1:${address.port}/xiaozhi/v1/`;
    let audioFrames = 0;
    let resolveAudio!: (frames: number) => void;
    const audioReceived = new Promise<number>((resolve) => { resolveAudio = resolve; });
    const response = new Promise<any>((resolve) => {
      server.once("connection", (socket, request) => {
        expect(request.headers["device-id"]).toBe("stackchan-sim-001");
        expect(request.headers["protocol-version"]).toBe("1");
        let receivedHello = false;
        socket.on("message", (raw, binary) => {
          if (binary) { audioFrames += 1; return; }
          const message = JSON.parse(raw.toString());
          if (!receivedHello) {
            receivedHello = true;
            expect(message.type).toBe("hello");
            expect(message.audio_params).toMatchObject({ sample_rate: 16000, frame_duration: 60 });
            socket.send(JSON.stringify({ type: "hello", session_id: "test-session", transport: "websocket", audio_params: { format: "opus", sample_rate: 24000 } }));
            socket.send(JSON.stringify({ type: "mcp", payload: { jsonrpc: "2.0", method: "initialize", params: { protocolVersion: "2024-11-05" }, id: 1 } }));
          } else if (message.type === "mcp" && message.payload?.id === 1) {
            expect(message.payload.result.capabilities).toEqual({ tools: {} });
            socket.send(JSON.stringify({ type: "mcp", payload: { jsonrpc: "2.0", method: "tools/list", params: {}, id: 7 } }));
          } else if (message.type === "mcp" && message.payload?.id === 7) {
            resolve(message);
            socket.send(JSON.stringify({ type: "stt", text: "你好，我是测试设备" }));
            socket.send(JSON.stringify({ type: "tts", state: "sentence_start", text: "你好，很高兴见到你" }));
            const encoder = new OpusScript(24000, 1, OpusScript.Application.AUDIO);
            const pcm = Buffer.alloc(1440 * 2);
            for (let index = 0; index < 1440; index += 1) pcm.writeInt16LE(Math.round(Math.sin(index / 16) * 4000), index * 2);
            socket.send(encoder.encode(pcm, 1440));
            encoder.delete();
          }
          else if (message.type === "listen" && message.state === "stop") resolveAudio(audioFrames);
        });
      });
    });
    const { StackChanDevice, DEVICE_TOOLS } = await import("./device.js");
    const device = new StackChanDevice(new LogStore());
    const uiMessages: any[] = [];
    device.subscribe((message) => uiMessages.push(message));
    await device.connect();
    const message = await response;
    expect(message.session_id).toBe("test-session");
    expect(message.payload.result.tools).toHaveLength(DEVICE_TOOLS.length);
    await device.sendSample("zh-greeting");
    expect(await audioReceived).toBeGreaterThan(10);
    await vi.waitFor(() => {
      expect(uiMessages).toContainEqual(expect.objectContaining({ type: "transcript", role: "user", text: "你好，我是测试设备" }));
      expect(uiMessages).toContainEqual(expect.objectContaining({ type: "transcript", role: "assistant", text: "你好，很高兴见到你", append: true }));
      expect(uiMessages).toContainEqual(expect.objectContaining({ type: "audio" }));
      expect(uiMessages).toContainEqual(expect.objectContaining({ type: "transport", transport: expect.objectContaining({ downlinkFrames: 1 }) }));
    });
    device.disconnect();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  it("renders state-changing MCP tools and validates camera uploads", async () => {
    const { StackChanDevice } = await import("./device.js");
    const device = new StackChanDevice(new LogStore());
    await device.callTool("self.robot.set_head_angles", { yaw: 22, pitch: 61, speed: 300 });
    await device.callTool("self.robot.set_toggle", { name: "smart_mode", enabled: true });
    await device.callTool("self.robot.set_led_color", { color: "#ff0000" });
    expect(device.state).toMatchObject({ yaw: 22, pitch: 61, speed: 300, smartMode: true });
    expect(new Set(device.state.leds)).toEqual(new Set(["#ff0000"]));
    expect(() => device.setPhoto(Buffer.alloc(1), "text/plain")).toThrow(/JPEG and PNG/);
    expect(() => device.setPhoto(Buffer.alloc(5 * 1024 * 1024 + 1), "image/jpeg")).toThrow(/5 MB/);
    await expect(device.callTool("self.unknown", {})).rejects.toThrow(/method not found/);
  });

  it("round-trips a 60 ms Opus frame", () => {
    const pcm = Buffer.alloc(960 * 2);
    for (let index = 0; index < 960; index += 1) pcm.writeInt16LE(Math.round(Math.sin(index / 12) * 5000), index * 2);
    const encoder = new OpusScript(16000, 1, OpusScript.Application.VOIP);
    const decoder = new OpusScript(16000, 1, OpusScript.Application.AUDIO);
    const opus = encoder.encode(pcm, 960);
    const decoded = decoder.decode(opus);
    expect(opus.length).toBeGreaterThan(4);
    expect(decoded.length).toBe(1920);
    encoder.delete(); decoder.delete();
  });

  it("ships valid static bilingual PCM speech samples", async () => {
    const { wavPcm16k } = await import("./device.js");
    for (const name of ["en-greeting", "en-question", "zh-greeting", "zh-question"]) {
      const wav = await readFile(new URL(`../audio/${name}.wav`, import.meta.url));
      const pcm = wavPcm16k(wav);
      expect(pcm.length).toBeGreaterThan(8000);
      expect(pcm.some((sample) => Math.abs(sample) > 500)).toBe(true);
    }
  });
});
