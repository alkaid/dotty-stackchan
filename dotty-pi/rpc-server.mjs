#!/usr/bin/env node
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { spawnSync } from "node:child_process";
import { once } from "node:events";
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { pathToFileURL } from "node:url";

import {
  effectiveRuntimeEnv,
} from "./runtime-config.mjs";

const PORT = Number(process.env.DOTTY_PI_RPC_PORT ?? "8091");
const TURN_TIMEOUT_MS = Number(process.env.DOTTY_PI_TURN_TIMEOUT_MS ?? "120000");
const THINKING_LEVELS = new Set([
  "off", "minimal", "low", "medium", "high", "xhigh",
]);

function boolEnv(env, name, fallback) {
  const value = (env[name] ?? String(fallback)).trim().toLowerCase();
  return ["1", "true", "yes", "on"].includes(value);
}

export function loadActiveRole(env = process.env) {
  const path = env.DOTTY_ROLES_FILE
    ?? "/var/lib/dotty-bridge/state/roles.json";
  try {
    const state = JSON.parse(readFileSync(path, "utf8"));
    const role = state.roles.find(
      (candidate) => candidate.id === state.active_role_id,
    );
    if (role && typeof role.prompt === "string" && role.prompt.trim()) {
      return role;
    }
  } catch {
    // A missing store is the expected state before the first Bridge edit.
  }
  const promptPath = env.DOTTY_PI_SYSTEM_PROMPT_FILE
    ?? "/opt/dotty-pi/personas/default.md";
  const prompt = readFileSync(promptPath, "utf8").trim();
  if (!prompt) throw new Error("default role prompt is empty");
  return { id: "default", name: "Dotty", prompt, voice_id: "default" };
}

export function resolveSystemPrompt(env = effectiveRuntimeEnv()) {
  return loadActiveRole(env).prompt.trim();
}

function simpleThinkingLevel(env) {
  if (!boolEnv(env, "DOTTY_PI_SIMPLE_REASONING", false)) return "off";
  const level = (env.DOTTY_PI_SIMPLE_REASONING_EFFORT ?? "medium")
    .trim()
    .toLowerCase() || "medium";
  if (!THINKING_LEVELS.has(level) || level === "off") {
    throw new Error(
      `DOTTY_PI_SIMPLE_REASONING_EFFORT must be minimal, low, medium, high, or xhigh, got ${JSON.stringify(level)}`,
    );
  }
  return level;
}
export function buildPiArgs(env = effectiveRuntimeEnv()) {
  const systemPrompt = resolveSystemPrompt(env);
  const extra = (env.DOTTY_PI_EXTRA_FLAGS ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return [
    "--mode", "rpc",
    "--provider", env.DOTTY_PI_PROVIDER ?? "sub2api",
    "--model", env.DOTTY_PI_MODEL ?? "dotty-simple",
    "--no-session",
    "--no-builtin-tools",
    "--no-context-files",
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--system-prompt", systemPrompt,
    "--thinking", simpleThinkingLevel(env),
    ...extra,
  ];
}

export class PiRpc {
  constructor() {
    this.proc = null;
    this.nextId = 0;
    this.queue = [];
    this.waiters = [];
    this.stderr = [];
    this.configFingerprint = null;
    this.activeTurnId = null;
    this.abortedTurnIds = new Set();
  }

  start() {
    const env = effectiveRuntimeEnv();
    const args = buildPiArgs(env);
    const fingerprint = JSON.stringify(args);
    if (
      this.proc
      && this.proc.exitCode === null
      && this.configFingerprint === fingerprint
    ) return;
    if (this.proc && this.proc.exitCode === null) this.proc.kill("SIGTERM");

    const renderPath = new URL("./render-models-json.mjs", import.meta.url).pathname;
    const rendered = spawnSync(process.execPath, [renderPath], {
      env,
      encoding: "utf8",
    });
    if (rendered.status !== 0) {
      throw new Error(
        `failed to render models.json: ${(rendered.stderr || rendered.stdout || "unknown error").trim()}`,
      );
    }

    this.queue = [];
    this.stderr = [];
    this.activeTurnId = null;
    this.abortedTurnIds.clear();
    this.proc = spawn("pi", args, {
      stdio: ["pipe", "pipe", "pipe"],
      env,
    });
    this.configFingerprint = fingerprint;
    createInterface({ input: this.proc.stdout }).on("line", (line) => {
      if (!line.trim()) return;
      try {
        this.route(JSON.parse(line));
      } catch {
        // pi sometimes writes diagnostics to stdout. They are not RPC frames.
      }
    });
    createInterface({ input: this.proc.stderr }).on("line", (line) => {
      this.stderr.push(line);
      if (this.stderr.length > 200) this.stderr.shift();
    });
  }

  async health() {
    if (!this.proc || this.proc.exitCode !== null) this.start();
    await new Promise((resolve) => setTimeout(resolve, 150));
    if (!this.proc || this.proc.exitCode !== null) {
      const detail = this.stderr.slice(-3).join(" | ") || "no stderr";
      throw new Error(`pi process is not running: ${detail}`);
    }
  }

  route(frame) {
    if (frame?.type === "extension_ui_request") {
      this.handleUi(frame);
      return;
    }
    const waiter = this.waiters[0];
    if (waiter) waiter(frame);
    else this.queue.push(frame);
  }

  handleUi(req) {
    if (["select", "confirm", "input", "editor"].includes(req.method)) {
      this.send({ type: "extension_ui_response", id: req.id ?? "", cancelled: true });
    }
  }

  send(frame) {
    this.start();
    this.proc.stdin.write(`${JSON.stringify(frame)}\n`);
  }

  async nextFrame(timeoutMs) {
    if (this.queue.length) return this.queue.shift();
    return new Promise((resolve, reject) => {
      const waiter = (frame) => {
        clearTimeout(timer);
        this.waiters = this.waiters.filter((candidate) => candidate !== waiter);
        resolve(frame);
      };
      const timer = setTimeout(() => {
        this.waiters = this.waiters.filter((candidate) => candidate !== waiter);
        reject(new Error("timeout"));
      }, timeoutMs);
      this.waiters.push(waiter);
    });
  }

  nextIdFor(prefix) {
    this.nextId += 1;
    return `${prefix}-${this.nextId}`;
  }

  async newSession() {
    const id = this.nextIdFor("nsess");
    this.send({ id, type: "new_session" });
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      const frame = await this.nextFrame(10000);
      if (frame?.type === "response" && frame.command === "new_session" && frame.id === id) return;
    }
    throw new Error("new_session timed out");
  }

  abort() {
    if (this.activeTurnId) this.abortedTurnIds.add(this.activeTurnId);
    const id = this.nextIdFor("abort");
    this.send({ id, type: "abort" });
  }

  async turn(message, onText) {
    const id = this.nextIdFor("turn");
    this.send({ id, type: "prompt", message });
    this.activeTurnId = id;
    try {
      let sawAccept = false;
      const deadline = Date.now() + TURN_TIMEOUT_MS;
      while (Date.now() < deadline) {
        const frame = await this.nextFrame(Math.max(1, deadline - Date.now()));
        if (frame?.type === "response" && frame.command === "prompt" && frame.id === id) {
          if (!frame.success) throw new Error(`pi rejected prompt: ${frame.error ?? "unknown"}`);
          sawAccept = true;
          continue;
        }
        if (frame?.type === "response" && frame.command === "abort" && frame.success) {
          if (this.abortedTurnIds.has(id)) return;
          continue;
        }
        if (frame?.type === "message_update") {
          const event = frame.assistantMessageEvent;
          if (event?.type === "text_delta" && event.delta) onText(event.delta);
          if (event?.type === "toolcall_end") {
            const toolCall = event.toolCall ?? {};
            console.log(
              `dotty-pi tool call name=${toolCall.name ?? "unknown"} id=${toolCall.id ?? "unknown"}`,
            );
          }
          continue;
        }
        if (frame?.type === "agent_end") {
          if (!sawAccept) throw new Error("agent_end before prompt-accept");
          return;
        }
      }
      throw new Error("turn timed out");
    } finally {
      if (this.activeTurnId === id) this.activeTurnId = null;
      this.abortedTurnIds.delete(id);
    }
  }
}

function json(res, status, body) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

async function readJson(req) {
  let body = "";
  req.setEncoding("utf8");
  req.on("data", (chunk) => { body += chunk; });
  await once(req, "end");
  return body ? JSON.parse(body) : {};
}

export function createRpcServer(rpc = new PiRpc()) {
  let busy = false;
  let activeOperation = null;
  let activeTurn = null;

  async function cancelActiveTurn() {
    const turn = activeTurn;
    if (!turn) return;
    await rpc.abort();
    try {
      await turn;
    } catch {
      // Aborted turns may reject; either outcome releases the RPC process.
    }
    if (activeTurn === turn) activeTurn = null;
    if (activeOperation === turn) {
      activeOperation = null;
      busy = false;
    }
  }

  return createServer(async (req, res) => {
    let ownsRpc = false;
    let operation = null;
    try {
      if (req.method === "GET" && req.url === "/health") {
        await rpc.health();
        json(res, 200, { ok: true });
        return;
      }
      if (req.method === "POST" && req.url === "/new_session") {
        await cancelActiveTurn();
        if (busy) {
          json(res, 409, { error: "rpc operation already in progress" });
          return;
        }
        busy = true;
        ownsRpc = true;
        operation = rpc.newSession();
        activeOperation = operation;
        await operation;
        json(res, 200, { ok: true });
        return;
      }
      if (req.method === "POST" && req.url === "/turn") {
        await cancelActiveTurn();
        if (busy) {
          json(res, 409, { error: "rpc operation already in progress" });
          return;
        }
        busy = true;
        ownsRpc = true;
        const body = await readJson(req);
        const message = String(body.message ?? "");
        if (!message.trim()) {
          json(res, 400, { error: "message required" });
          return;
        }
        res.writeHead(200, { "content-type": "text/plain; charset=utf-8" });
        operation = rpc.turn(message, (delta) => res.write(delta));
        activeOperation = operation;
        activeTurn = operation;
        await operation;
        res.end();
        return;
      }
      json(res, 404, { error: "not found" });
    } catch (err) {
      if (!res.headersSent) {
        json(res, 500, { error: String(err?.message ?? err) });
      } else {
        res.end();
      }
    } finally {
      if (ownsRpc && activeOperation === operation) {
        activeOperation = null;
        if (activeTurn === operation) activeTurn = null;
        busy = false;
      }
    }
  });
}

export function listen(port = PORT) {
  const server = createRpcServer();
  return server.listen(port, "0.0.0.0", () => {
    console.log(`dotty-pi rpc server listening on :${port}`);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  listen();
}
