import { access } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import Fastify, { type FastifyInstance } from "fastify";
import multipart from "@fastify/multipart";
import staticPlugin from "@fastify/static";
import websocket from "@fastify/websocket";
import { buildCatalog, DECLARED_CATALOG, SERVICE_BASES } from "./catalog.js";
import { StackChanDevice } from "./device.js";
import { LogStore } from "./log-store.js";
import type { ApiCard } from "./types.js";

interface ExecuteBody {
  path?: Record<string, string | number>;
  query?: Record<string, string | number | boolean>;
  headers?: Record<string, string>;
  body?: unknown;
  file?: { name: string; mime: string; data: string };
}

const SECRET_HEADER = /^(authorization|x-admin-token|cookie|host)$/i;

export async function createApp(): Promise<FastifyInstance> {
  const app = Fastify({ logger: true, bodyLimit: 7 * 1024 * 1024 });
  const logs = new LogStore();
  const device = new StackChanDevice(logs);
  let catalog = await buildCatalog();

  await app.register(multipart, { limits: { fileSize: 5 * 1024 * 1024, files: 1 } });
  await app.register(websocket);

  app.get("/health", async () => ({ ok: true, service: "stackchan-simulator", connected: device.state.connected }));
  app.get("/api/catalog", async () => ({ ...catalog, counts: countServices(catalog.cards), generatedAt: new Date().toISOString() }));
  app.post("/api/catalog/refresh", async () => { catalog = await buildCatalog(); return catalog; });

  async function execute(card: ApiCard, input: ExecuteBody = {}) {
    const started = performance.now();
    let path = card.path;
    for (const [key, value] of Object.entries(input.path || {})) {
      path = path.replace(`{${key}}`, encodeURIComponent(String(value)));
    }
    if (/{[^}]+}/.test(path)) throw new Error("all path parameters are required");
    const target = new URL(path, SERVICE_BASES[card.service]);
    for (const [key, value] of Object.entries(input.query || {})) {
      if (value !== "" && value !== undefined) target.searchParams.set(key, String(value));
    }
    const headers = new Headers();
    for (const [key, value] of Object.entries(input.headers || {})) {
      if (!SECRET_HEADER.test(key) && value) headers.set(key, value);
    }
    const token = process.env.DOTTY_ADMIN_TOKEN?.trim();
    if (token && (card.service === "xiaozhi" || card.service === "bridge")) headers.set("X-Admin-Token", token);
    const init: RequestInit = { method: card.method, headers, signal: AbortSignal.timeout(card.stream ? 30000 : 65000) };
    if (card.method !== "GET") {
      if (card.contentType === "multipart") {
        const form = new FormData();
        if (input.body && typeof input.body === "object") {
          for (const [key, value] of Object.entries(input.body as Record<string, unknown>)) form.set(key, String(value));
        }
        if (input.file) {
          const bytes = Buffer.from(input.file.data, "base64");
          if (bytes.length > 5 * 1024 * 1024) throw new Error("file exceeds 5 MB");
          form.set("file", new Blob([bytes], { type: input.file.mime }), input.file.name);
        }
        init.body = form;
      } else {
        headers.set("Content-Type", "application/json");
        init.body = JSON.stringify(input.body ?? {});
      }
    }
    logs.add({ direction: "out", service: card.service, deviceId: device.state.deviceId, kind: "HTTP", summary: `${card.method} ${card.path}`, payload: { url: target.pathname, query: input.query, body: input.body } });
    const response = await fetch(target, init);
    const bytes = card.stream ? await readBoundedStream(response) : Buffer.from(await response.arrayBuffer());
    const durationMs = Math.round(performance.now() - started);
    const contentType = response.headers.get("content-type") || "application/octet-stream";
    let preview: unknown;
    let encoding: "json" | "text" | "base64" = "text";
    if (contentType.includes("json")) {
      try { preview = JSON.parse(bytes.toString("utf8")); encoding = "json"; }
      catch { preview = bytes.toString("utf8"); }
    } else if (contentType.startsWith("text/") || contentType.includes("event-stream")) {
      preview = bytes.toString("utf8");
    } else {
      preview = bytes.toString("base64"); encoding = "base64";
    }
    logs.add({ direction: "in", service: card.service, deviceId: device.state.deviceId, kind: "HTTP", summary: `${response.status} ${card.method} ${card.path}`, payload: preview, binaryLength: encoding === "base64" ? bytes.length : undefined, durationMs });
    return {
      status: response.status,
      ok: response.ok,
      durationMs,
      headers: Object.fromEntries(response.headers.entries()),
      contentType,
      encoding,
      body: preview,
    };
  }

  app.post<{ Params: { id: string }; Body: ExecuteBody }>("/api/execute/:id", async (request, reply) => {
    const card = DECLARED_CATALOG.find((item) => item.id === request.params.id);
    if (!card) return reply.code(404).send({ error: "unknown catalog id" });
    try { return await execute(card, request.body || {}); }
    catch (error) { return reply.code(502).send({ error: String((error as Error).message || error) }); }
  });

  app.post("/api/smoke", async () => {
    const results = [];
    for (const card of DECLARED_CATALOG.filter((item) => item.smoke)) {
      try { const result = await execute(card, defaultInput(card, device.state.deviceId)); results.push({ id: card.id, ok: result.ok, status: result.status, durationMs: result.durationMs }); }
      catch (error) { results.push({ id: card.id, ok: false, error: String((error as Error).message || error) }); }
    }
    return { ok: results.every((item) => item.ok), results };
  });

  app.get("/api/device/state", async () => ({
    state: device.state,
    samples: device.sampleNames,
    asrLanguage: process.env.STACKCHAN_SIMULATOR_ASR_LANGUAGE || process.env.ASR_LANGUAGE || "en",
  }));
  app.post("/api/device/connect", async (_request, reply) => { try { await device.connect(); return { ok: true, state: device.state }; } catch (error) { return reply.code(502).send({ error: String((error as Error).message || error) }); } });
  app.post("/api/device/disconnect", async () => { device.disconnect(); return { ok: true }; });
  app.post<{ Body: { name: string } }>("/api/device/audio/send", async (request, reply) => { try { await device.sendSample(request.body?.name); return { ok: true }; } catch (error) { return reply.code(400).send({ error: String((error as Error).message || error) }); } });
  app.post<{ Body: { name: string; question?: string } }>("/api/device/audio/explain", async (request, reply) => { try { return await device.submitAudio(request.body?.name, request.body?.question || "Describe what you hear."); } catch (error) { return reply.code(502).send({ error: String((error as Error).message || error) }); } });
  app.post<{ Body: { name: string; data?: Record<string, unknown> } }>("/api/device/event", async (request, reply) => { try { device.sendEvent(request.body?.name, request.body?.data || {}); return { ok: true }; } catch (error) { return reply.code(400).send({ error: String((error as Error).message || error) }); } });
  app.post<{ Body: Record<string, unknown> }>("/api/device/mcp", async (request, reply) => { try { device.sendRawMcp(request.body || {}); return { ok: true }; } catch (error) { return reply.code(400).send({ error: String((error as Error).message || error) }); } });
  app.post("/api/device/photo", async (request, reply) => {
    try {
      const part = await request.file();
      if (!part) return reply.code(400).send({ error: "file required" });
      const bytes = await part.toBuffer();
      device.setPhoto(bytes, part.mimetype);
      return { ok: true, bytes: bytes.length, type: part.mimetype };
    } catch (error) { return reply.code(400).send({ error: String((error as Error).message || error) }); }
  });

  app.get("/api/logs", async () => logs.list());
  app.delete("/api/logs", async () => { logs.clear(); return { ok: true }; });
  app.get("/api/logs/export", async (_request, reply) => reply.type("application/x-ndjson").header("Content-Disposition", "attachment; filename=stackchan-simulator.jsonl").send(logs.list().map((entry) => JSON.stringify(entry)).join("\n") + "\n"));

  app.get("/ws/ui", { websocket: true }, (socket) => {
    socket.send(JSON.stringify({ type: "snapshot", state: device.state, logs: logs.list() }));
    const offLog = logs.subscribe((entry) => socket.readyState === socket.OPEN && socket.send(JSON.stringify({ type: "log", entry })));
    const offDevice = device.subscribe((message) => socket.readyState === socket.OPEN && socket.send(JSON.stringify(message)));
    socket.on("close", () => { offLog(); offDevice(); });
  });

  const root = join(fileURLToPath(new URL("..", import.meta.url)), "dist");
  try {
    await access(root);
    await app.register(staticPlugin, { root, wildcard: false });
    app.setNotFoundHandler((request, reply) => request.raw.url?.startsWith("/api/") ? reply.code(404).send({ error: "not found" }) : reply.sendFile("index.html"));
  } catch {
    app.get("/", async () => ({ service: "stackchan-simulator", ui: "run npm build first" }));
  }
  return app;
}

function defaultInput(card: ApiCard, deviceId: string): ExecuteBody {
  const path: Record<string, string> = {};
  const query: Record<string, string> = {};
  for (const parameter of card.parameters || []) {
    const value = parameter.name === "device_id" ? deviceId : parameter.name === "limit" ? "5" : "";
    if (parameter.in === "path") path[parameter.name] = value;
    if (parameter.in === "query" && value) query[parameter.name] = value;
  }
  return { path, query };
}

function countServices(cards: ApiCard[]): Record<string, number> {
  return cards.reduce<Record<string, number>>((counts, card) => { counts[card.service] = (counts[card.service] || 0) + 1; return counts; }, {});
}

async function readBoundedStream(response: Response): Promise<Buffer> {
  if (!response.body) return Buffer.alloc(0);
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (size < 256 * 1024) {
      const next = await Promise.race([
        reader.read(),
        new Promise<{ done: true; value?: undefined }>((resolve) => setTimeout(() => resolve({ done: true }), 1500)),
      ]);
      if (next.done) break;
      chunks.push(next.value); size += next.value.length;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  return Buffer.concat(chunks.map((chunk) => Buffer.from(chunk)), size);
}
