import { readFile } from "node:fs/promises";
import { basename, join } from "node:path";
import OpusScript from "opusscript";
import WebSocket from "ws";
import type { LogStore } from "./log-store.js";
import type { DeviceState } from "./types.js";
import { SERVICE_BASES } from "./catalog.js";

const DEVICE_ID = process.env.STACKCHAN_DEVICE_ID || "stackchan-sim-001";
const AUDIO_DIR = process.env.STACKCHAN_AUDIO_DIR || join(process.cwd(), "audio");
const SAMPLE_NAMES = ["en-greeting", "en-question", "zh-greeting", "zh-question"];
const DEFAULT_PHOTO = Buffer.from(
  "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAb/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAAB//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EH//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q==",
  "base64",
);

export const DEVICE_TOOLS = [
  { name: "self.get_device_status", description: "Read simulated hardware status", inputSchema: { type: "object", properties: {} } },
  { name: "self.audio_speaker.set_volume", description: "Set speaker volume", inputSchema: { type: "object", properties: { volume: { type: "integer", minimum: 0, maximum: 100 } }, required: ["volume"] } },
  { name: "self.robot.set_state", description: "Set high-level robot state", inputSchema: { type: "object", properties: { state: { type: "string" } }, required: ["state"] } },
  { name: "self.robot.set_toggle", description: "Set kid or smart mode", inputSchema: { type: "object", properties: { name: { type: "string" }, enabled: { type: "boolean" } }, required: ["name", "enabled"] } },
  { name: "self.robot.set_head_angles", description: "Set head yaw, pitch and speed", inputSchema: { type: "object", properties: { yaw: { type: "number" }, pitch: { type: "number" }, speed: { type: "number" } } } },
  { name: "self.robot.set_led_color", description: "Set all LED colors", inputSchema: { type: "object", properties: { color: { type: "string" } }, required: ["color"] } },
  { name: "self.robot.set_led_multi", description: "Set individual LED colors", inputSchema: { type: "object", properties: { colors: { type: "array", items: { type: "string" } } }, required: ["colors"] } },
  { name: "self.robot.set_face_identified", description: "Pulse the face identification LED", inputSchema: { type: "object", properties: {} } },
  { name: "self.camera.take_photo", description: "Capture and explain a still image", inputSchema: { type: "object", properties: { question: { type: "string" } } } },
  { name: "self.audio.capture_clip", description: "Capture and explain microphone audio", inputSchema: { type: "object", properties: { duration_ms: { type: "integer" } } } },
];

export function resolveWsUrl(env: NodeJS.ProcessEnv = process.env): string {
  const explicit = env.XIAOZHI_WS_URL?.trim();
  if (explicit) return explicit;
  const publishedPort = env.XIAOZHI_WS_PORT?.trim();
  if (publishedPort) return `ws://127.0.0.1:${publishedPort}/xiaozhi/v1/`;
  const publicBase = env.XIAOZHI_PUBLIC_WS_BASE_URL?.trim();
  if (publicBase) {
    if (/\/xiaozhi\/v1\/?$/.test(publicBase)) return publicBase;
    return `${publicBase.replace(/\/$/, "")}/xiaozhi/v1/`;
  }
  return "ws://127.0.0.1:8000/xiaozhi/v1/";
}

type Listener = (message: Record<string, unknown>) => void;

function initialState(): DeviceState {
  return {
    connected: false, deviceId: DEVICE_ID, sessionId: "", status: "offline",
    emotion: "neutral", subtitle: "", mouth: 0, yaw: 0, pitch: 45, speed: 250,
    volume: 65, mode: "idle", kidMode: true, smartMode: false,
    leds: Array(12).fill("#20252a"),
  };
}

function pcmRms(pcm: Buffer): number {
  if (pcm.length < 2) return 0;
  let sum = 0;
  const count = Math.floor(pcm.length / 2);
  for (let index = 0; index < count; index += 1) {
    const sample = pcm.readInt16LE(index * 2) / 32768;
    sum += sample * sample;
  }
  return Math.min(1, Math.sqrt(sum / count) * 4);
}

export function wavPcm16k(buffer: Buffer): Int16Array {
  if (buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error("invalid PCM WAV file");
  }
  let sampleRate = 0;
  let channels = 0;
  let bitsPerSample = 0;
  let data: Buffer<ArrayBufferLike> = Buffer.alloc(0);
  for (let offset = 12; offset + 8 <= buffer.length;) {
    const id = buffer.toString("ascii", offset, offset + 4);
    const size = Math.min(buffer.readUInt32LE(offset + 4), buffer.length - offset - 8);
    if (id === "fmt " && size >= 16) {
      if (buffer.readUInt16LE(offset + 8) !== 1) throw new Error("WAV must use PCM encoding");
      channels = buffer.readUInt16LE(offset + 10);
      sampleRate = buffer.readUInt32LE(offset + 12);
      bitsPerSample = buffer.readUInt16LE(offset + 22);
    } else if (id === "data") {
      data = buffer.subarray(offset + 8, offset + 8 + size);
    }
    offset += 8 + size + (size % 2);
  }
  if (!sampleRate || !channels || bitsPerSample !== 16 || !data.length) {
    throw new Error("WAV must contain 16-bit PCM audio");
  }
  const inputLength = Math.floor(data.length / (channels * 2));
  const mono = new Int16Array(inputLength);
  for (let frame = 0; frame < inputLength; frame += 1) {
    let sum = 0;
    for (let channel = 0; channel < channels; channel += 1) {
      sum += data.readInt16LE((frame * channels + channel) * 2);
    }
    mono[frame] = Math.round(sum / channels);
  }
  if (sampleRate === 16000) return mono;
  const output = new Int16Array(Math.max(1, Math.round(mono.length * 16000 / sampleRate)));
  for (let index = 0; index < output.length; index += 1) {
    const source = index * sampleRate / 16000;
    const left = Math.min(mono.length - 1, Math.floor(source));
    const right = Math.min(mono.length - 1, left + 1);
    const mix = source - left;
    output[index] = Math.round(mono[left] * (1 - mix) + mono[right] * mix);
  }
  return output;
}

export class StackChanDevice {
  readonly sampleNames = SAMPLE_NAMES;
  state = initialState();
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private decoder = new OpusScript(24000, 1, OpusScript.Application.AUDIO);
  private photo: Buffer<ArrayBufferLike> = DEFAULT_PHOTO;
  private photoType = "image/jpeg";
  private selectedSample = "en-greeting";
  private responseTimer: NodeJS.Timeout | null = null;
  private transport = { uplinkFrames: 0, uplinkBytes: 0, downlinkFrames: 0, downlinkBytes: 0 };

  constructor(private logs: LogStore) {}

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener({ type: "state", state: this.state });
    return () => this.listeners.delete(listener);
  }

  private emit(message: Record<string, unknown>): void {
    for (const listener of this.listeners) listener(message);
  }

  private update(patch: Partial<DeviceState>): void {
    this.state = { ...this.state, ...patch };
    this.emit({ type: "state", state: this.state });
  }

  private updateTransport(patch: Partial<typeof this.transport>): void {
    this.transport = { ...this.transport, ...patch };
    this.emit({ type: "transport", transport: this.transport });
  }

  private clearResponseTimer(): void {
    if (this.responseTimer) clearTimeout(this.responseTimer);
    this.responseTimer = null;
  }

  async connect(): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    await new Promise<void>((resolve, reject) => {
      const headers: Record<string, string> = {
        Authorization: `Bearer ${process.env.XIAOZHI_DEVICE_TOKEN || "stackchan-simulator"}`,
        "Protocol-Version": "1",
        "Device-Id": this.state.deviceId,
        "Client-Id": process.env.STACKCHAN_CLIENT_ID || "stackchan-simulator-client",
      };
      const ws = new WebSocket(resolveWsUrl(), { headers });
      this.ws = ws;
      const timer = setTimeout(() => reject(new Error("Xiaozhi WebSocket timeout")), 10000);
      ws.once("open", () => {
        clearTimeout(timer);
        this.update({ connected: true, status: "idle" });
        this.sendJson({
          type: "hello", version: 1, features: { mcp: true, aec: true }, transport: "websocket",
          audio_params: { format: "opus", sample_rate: 16000, channels: 1, frame_duration: 60 },
        });
        resolve();
      });
      ws.on("message", (data, isBinary) => void this.handleMessage(data as Buffer, isBinary));
      ws.on("close", () => {
        this.clearResponseTimer();
        this.ws = null;
        this.update({ connected: false, status: "offline", sessionId: "", mouth: 0 });
        this.logs.add({ direction: "local", service: "xiaozhi", deviceId: this.state.deviceId, kind: "WS", summary: "WebSocket closed" });
      });
      ws.on("error", (error) => {
        clearTimeout(timer);
        this.logs.add({ direction: "local", service: "xiaozhi", deviceId: this.state.deviceId, kind: "WS", summary: error.message });
        if (ws.readyState !== WebSocket.OPEN) reject(error);
      });
    });
  }

  disconnect(): void { this.ws?.close(1000, "operator disconnect"); }

  private sendJson(payload: Record<string, unknown>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) throw new Error("device is not connected");
    const frame = this.state.sessionId && !payload.session_id
      ? { session_id: this.state.sessionId, ...payload }
      : payload;
    this.ws.send(JSON.stringify(frame));
    this.logs.add({ direction: "out", service: "xiaozhi", deviceId: this.state.deviceId, kind: payload.type === "mcp" ? "MCP" : "WS", summary: String(payload.type || "json"), payload: frame });
  }

  private async handleMessage(data: Buffer, isBinary: boolean): Promise<void> {
    if (isBinary) {
      const decoded = Buffer.from(this.decoder.decode(data));
      const rms = pcmRms(decoded);
      this.updateTransport({
        downlinkFrames: this.transport.downlinkFrames + 1,
        downlinkBytes: this.transport.downlinkBytes + data.length,
      });
      this.update({ mouth: rms });
      this.emit({ type: "audio", sampleRate: 24000, pcm: decoded.toString("base64"), rms });
      this.logs.add({ direction: "in", service: "xiaozhi", deviceId: this.state.deviceId, kind: "AUDIO", summary: "Opus audio frame", binaryLength: data.length });
      setTimeout(() => this.update({ mouth: 0 }), 90);
      return;
    }
    let message: any;
    try { message = JSON.parse(data.toString("utf8")); }
    catch { this.logs.add({ direction: "in", service: "xiaozhi", deviceId: this.state.deviceId, kind: "WS", summary: data.toString("utf8").slice(0, 160) }); return; }
    this.logs.add({ direction: "in", service: "xiaozhi", deviceId: this.state.deviceId, kind: message.type === "mcp" ? "MCP" : "WS", summary: String(message.type || "json"), payload: message });
    if (message.type === "hello") this.update({ sessionId: message.session_id || "", status: "idle" });
    if (message.type === "stt") {
      this.clearResponseTimer();
      this.update({ subtitle: message.text ? `Heard: ${message.text}` : "", status: "thinking" });
      this.emit({ type: "transcript", role: "user", text: message.text || "", reset: true });
    }
    if (message.type === "llm") this.update({ emotion: message.emotion || "neutral" });
    if (message.type === "tts") {
      this.clearResponseTimer();
      const status = message.state === "stop" ? "idle" : "speaking";
      this.update({ status, subtitle: message.text ?? this.state.subtitle, mouth: status === "idle" ? 0 : this.state.mouth });
      if (message.state === "start") this.emit({ type: "transcript", role: "assistant", text: "", reset: true });
      if (message.text) this.emit({ type: "transcript", role: "assistant", text: message.text, append: true });
    }
    if (message.type === "alert") this.update({ emotion: message.emotion || "surprised", subtitle: message.message || "" });
    if (message.type === "system") this.emit({ type: "system", message });
    if (message.type === "mcp") await this.handleMcp(message.payload || {});
  }

  private mcpResult(id: unknown, result: unknown): void {
    this.sendJson({ type: "mcp", payload: { jsonrpc: "2.0", id, result } });
  }

  private mcpError(id: unknown, code: number, message: string): void {
    this.sendJson({ type: "mcp", payload: { jsonrpc: "2.0", id, error: { code, message } } });
  }

  private async handleMcp(payload: any): Promise<void> {
    if (payload.method === "initialize") {
      this.mcpResult(payload.id, {
        protocolVersion: payload.params?.protocolVersion || "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "stackchan-simulator", version: "0.1.0" },
      });
      return;
    }
    if (payload.method === "notifications/initialized") return;
    if (payload.method === "tools/list") {
      this.mcpResult(payload.id, { tools: DEVICE_TOOLS, nextCursor: "" });
      return;
    }
    if (payload.method !== "tools/call") {
      this.mcpError(payload.id, -32601, "Method not found");
      return;
    }
    const name = String(payload.params?.name || "");
    const args = payload.params?.arguments || {};
    try {
      const result = await this.callTool(name, args);
      this.mcpResult(payload.id, { content: [{ type: "text", text: JSON.stringify(result) }], isError: false });
    } catch (error) {
      this.mcpResult(payload.id, { content: [{ type: "text", text: String((error as Error).message || error) }], isError: true });
    }
  }

  async callTool(name: string, args: Record<string, any>): Promise<unknown> {
    if (name === "self.get_device_status") return this.state;
    if (name === "self.audio_speaker.set_volume") { this.update({ volume: Math.max(0, Math.min(100, Number(args.volume))) }); return true; }
    if (name === "self.robot.set_state") { this.update({ mode: String(args.state || "idle") }); return true; }
    if (name === "self.robot.set_toggle") {
      if (args.name === "kid_mode") this.update({ kidMode: Boolean(args.enabled) });
      else if (args.name === "smart_mode") this.update({ smartMode: Boolean(args.enabled) });
      else throw new Error("unknown toggle");
      return true;
    }
    if (name === "self.robot.set_head_angles") { this.update({ yaw: Number(args.yaw || 0), pitch: Number(args.pitch ?? 45), speed: Number(args.speed || 250) }); return true; }
    if (name === "self.robot.set_led_color") { this.update({ leds: Array(12).fill(String(args.color || "#ffffff")) }); return true; }
    if (name === "self.robot.set_led_multi") {
      const colors = Array.isArray(args.colors) ? args.colors.slice(0, 12).map(String) : [];
      this.update({ leds: [...colors, ...Array(12 - colors.length).fill("#20252a")] }); return true;
    }
    if (name === "self.robot.set_face_identified") { const leds = [...this.state.leds]; leds[8] = "#31d17c"; this.update({ leds }); setTimeout(() => this.update({ leds: initialState().leds }), 4000); return true; }
    if (name === "self.camera.take_photo") return this.submitPhoto(String(args.question || "What do you see?"));
    if (name === "self.audio.capture_clip") return this.submitAudio(this.selectedSample, String(args.question || "Describe what you hear."));
    throw new Error(`method not found: ${name}`);
  }

  setPhoto(bytes: Buffer, mime: string): void {
    if (bytes.length > 5 * 1024 * 1024) throw new Error("photo exceeds 5 MB");
    if (!new Set(["image/jpeg", "image/png"]).has(mime)) throw new Error("only JPEG and PNG are accepted");
    this.photo = bytes; this.photoType = mime;
  }

  private async submitPhoto(question: string): Promise<unknown> {
    const form = new FormData();
    form.set("question", question);
    form.set("file", new Blob([Uint8Array.from(this.photo).buffer], { type: this.photoType }), this.photoType === "image/png" ? "scene.png" : "scene.jpg");
    const response = await fetch(`${SERVICE_BASES.behaviour}/api/vision/explain`, { method: "POST", headers: { "Device-Id": this.state.deviceId }, body: form, signal: AbortSignal.timeout(60000) });
    if (!response.ok) throw new Error(`vision explain HTTP ${response.status}`);
    return response.json();
  }

  private async sampleBuffer(name: string): Promise<Buffer> {
    if (!SAMPLE_NAMES.includes(name)) throw new Error("unknown audio sample");
    return readFile(join(AUDIO_DIR, `${basename(name)}.wav`));
  }

  async sendSample(name: string): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) throw new Error("device is not connected");
    const wav = await this.sampleBuffer(name);
    this.selectedSample = name;
    const pcm = wavPcm16k(wav);
    const encoder = new OpusScript(16000, 1, OpusScript.Application.VOIP);
    this.emit({ type: "transcript_reset" });
    this.updateTransport({ uplinkFrames: 0, uplinkBytes: 0, downlinkFrames: 0, downlinkBytes: 0 });
    this.sendJson({ type: "listen", state: "start", mode: "manual" });
    this.update({ status: "listening", subtitle: `Sample: ${name}` });
    for (let offset = 0; offset < pcm.length; offset += 960) {
      const frame = new Int16Array(960);
      frame.set(pcm.subarray(offset, Math.min(offset + 960, pcm.length)));
      const encoded = Buffer.from(encoder.encode(Buffer.from(frame.buffer), 960));
      this.ws.send(encoded);
      this.updateTransport({
        uplinkFrames: this.transport.uplinkFrames + 1,
        uplinkBytes: this.transport.uplinkBytes + encoded.length,
      });
      this.logs.add({ direction: "out", service: "xiaozhi", deviceId: this.state.deviceId, kind: "AUDIO", summary: `Opus sample ${name}`, binaryLength: encoded.length });
      await new Promise((resolve) => setTimeout(resolve, 60));
    }
    encoder.delete();
    this.sendJson({ type: "listen", state: "stop", mode: "manual" });
    this.update({ status: "thinking" });
    this.clearResponseTimer();
    this.responseTimer = setTimeout(() => {
      if (this.state.status === "thinking") {
        this.update({ status: "idle", subtitle: "No STT/TTS response after 45 seconds" });
      }
    }, 45000);
  }

  async submitAudio(name: string, question: string): Promise<unknown> {
    this.selectedSample = name;
    const wav = await this.sampleBuffer(name);
    const form = new FormData();
    form.set("question", question);
    form.set("file", new Blob([Uint8Array.from(wav).buffer], { type: "audio/wav" }), `${name}.wav`);
    const response = await fetch(`${SERVICE_BASES.behaviour}/api/audio/explain`, { method: "POST", headers: { "Device-Id": this.state.deviceId }, body: form, signal: AbortSignal.timeout(60000) });
    if (!response.ok) throw new Error(`audio explain HTTP ${response.status}`);
    return response.json();
  }

  sendEvent(name: string, data: Record<string, unknown>): void { this.sendJson({ type: "event", name, data }); }
  sendRawMcp(payload: Record<string, unknown>): void { this.sendJson({ type: "mcp", payload }); }
}
