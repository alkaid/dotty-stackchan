import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  buildPiArgs,
  createRpcServer,
  loadActiveRole,
  PiRpc,
} from "../rpc-server.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function frameStream() {
  const queued = [];
  const waiters = [];
  return {
    next() {
      if (queued.length) return Promise.resolve(queued.shift());
      return new Promise((resolve) => waiters.push(resolve));
    },
    push(frame) {
      const resolve = waiters.shift();
      if (resolve) resolve(frame);
      else queued.push(frame);
    },
  };
}

async function withServer(rpc, run) {
  const server = createRpcServer(rpc);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test("pi starts with the baked persona and explicit Dotty extension", () => {
  const dir = mkdtempSync(join(tmpdir(), "dotty-pi-test-"));
  const promptPath = join(dir, "persona.md");
  writeFileSync(promptPath, "You are Dotty.\n");
  try {
    const args = buildPiArgs({
      DOTTY_PI_SYSTEM_PROMPT_FILE: promptPath,
      DOTTY_ROLES_FILE: join(dir, "missing-roles.json"),
      DOTTY_PI_PROVIDER: "sub2api",
      DOTTY_PI_MODEL: "dotty-simple",
    });
    assert.ok(args.includes("--no-builtin-tools"));
    assert.equal(
      args[args.indexOf("--extension") + 1],
      "/opt/dotty-pi/extensions/dotty-pi-ext/src/index.ts",
    );
    assert.equal(args[args.indexOf("--system-prompt") + 1], "You are Dotty.");
    assert.equal(args[args.indexOf("--thinking") + 1], "off");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("active role selects the prompt independently of Kid and Smart modes", () => {
  const dir = mkdtempSync(join(tmpdir(), "dotty-pi-test-"));
  const rolesPath = join(dir, "roles.json");
  const kidPath = join(dir, "kid-mode");
  const smartPath = join(dir, "smart-mode");
  const env = {
    DOTTY_ROLES_FILE: rolesPath,
    DOTTY_KID_MODE_STATE: kidPath,
    DOTTY_SMART_MODE_STATE: smartPath,
  };
  try {
    writeFileSync(rolesPath, JSON.stringify({
      active_role_id: "guide",
      roles: [
        { id: "default", name: "Dotty", prompt: "Default role" },
        { id: "guide", name: "Guide", prompt: "Guide role", voice_id: "edge" },
      ],
    }));
    writeFileSync(kidPath, "true");
    writeFileSync(smartPath, "true");
    assert.equal(loadActiveRole(env).id, "guide");
    const args = buildPiArgs(env);
    assert.equal(
      args[args.indexOf("--system-prompt") + 1],
      "Guide role",
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("simple route reasoning selects the configured pi thinking level", () => {
  const dir = mkdtempSync(join(tmpdir(), "dotty-pi-test-"));
  const promptPath = join(dir, "persona.md");
  writeFileSync(promptPath, "You are Dotty.\n");
  try {
    const args = buildPiArgs({
      DOTTY_PI_SYSTEM_PROMPT_FILE: promptPath,
      DOTTY_ROLES_FILE: join(dir, "missing-roles.json"),
      DOTTY_PI_SIMPLE_REASONING: "true",
      DOTTY_PI_SIMPLE_REASONING_EFFORT: "high",
    });
    assert.equal(args[args.indexOf("--thinking") + 1], "high");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("tool completion is logged without arguments on the live HTTP RPC path", async () => {
  const rpc = new PiRpc();
  rpc.send = () => {};
  const frames = [
    { type: "response", command: "prompt", id: "turn-1", success: true },
    {
      type: "message_update",
      assistantMessageEvent: {
        type: "toolcall_end",
        toolCall: { id: "tool-7", name: "remember", arguments: { secret: "value" } },
      },
    },
    { type: "agent_end" },
  ];
  rpc.nextFrame = async () => frames.shift();
  const lines = [];
  const originalLog = console.log;
  console.log = (line) => lines.push(String(line));
  try {
    await rpc.turn("remember this", () => {});
  } finally {
    console.log = originalLog;
  }
  assert.deepEqual(lines, ["dotty-pi tool call name=remember id=tool-7"]);
  assert.doesNotMatch(lines[0], /secret|value/);
});

test("an abort response terminates the active Pi RPC turn", async () => {
  const rpc = new PiRpc();
  const sent = [];
  const frames = frameStream();
  rpc.send = (frame) => sent.push(frame);
  rpc.nextFrame = () => frames.next();

  const turn = rpc.turn("first", () => assert.fail("aborted turn emitted text"));
  frames.push({ type: "response", command: "prompt", id: "turn-1", success: true });
  rpc.abort();
  frames.push({ type: "response", command: "abort", id: "abort-2", success: true });

  await turn;
  assert.deepEqual(sent.map((frame) => frame.type), ["prompt", "abort"]);
});

test("a late abort response cannot terminate the replacement turn", async () => {
  const rpc = new PiRpc();
  const sent = [];
  const frames = frameStream();
  rpc.send = (frame) => sent.push(frame);
  rpc.nextFrame = () => frames.next();

  const first = rpc.turn("first", () => assert.fail("aborted turn emitted text"));
  frames.push({ type: "response", command: "prompt", id: "turn-1", success: true });
  rpc.abort();
  frames.push({ type: "agent_end" });
  await first;

  const output = [];
  const replacement = rpc.turn("replacement", (text) => output.push(text));
  frames.push({ type: "response", command: "abort", id: "abort-2", success: true });
  frames.push({ type: "response", command: "prompt", id: "turn-3", success: true });
  frames.push({
    type: "message_update",
    assistantMessageEvent: { type: "text_delta", delta: "SECOND_OK" },
  });
  frames.push({ type: "agent_end" });

  await replacement;
  assert.deepEqual(output, ["SECOND_OK"]);
});

test("a new turn aborts the active turn while health leaves it alone", async () => {
  const started = deferred();
  const release = deferred();
  let abortCalls = 0;
  const rpc = {
    async health() {},
    async newSession() {},
    abort() {
      abortCalls += 1;
      release.resolve();
    },
    async turn(message, onText) {
      if (message === "first") {
        started.resolve();
        await release.promise;
        return;
      }
      onText(message);
    },
  };

  await withServer(rpc, async (baseUrl) => {
    const first = fetch(`${baseUrl}/turn`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "first" }),
    });
    await started.promise;

    const health = await fetch(`${baseUrl}/health`);
    assert.equal(health.status, 200);
    assert.equal(abortCalls, 0);

    const second = await fetch(`${baseUrl}/turn`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "second" }),
    });
    assert.equal(second.status, 200);
    assert.equal(await second.text(), "second");
    assert.equal(abortCalls, 1);
    assert.equal(await (await first).text(), "");
  });
});

test("new_session aborts an active turn before resetting", async () => {
  const started = deferred();
  const release = deferred();
  let abortCalls = 0;
  let resetCalls = 0;
  const rpc = {
    async health() {},
    async newSession() { resetCalls += 1; },
    abort() {
      abortCalls += 1;
      release.resolve();
    },
    async turn() {
      started.resolve();
      await release.promise;
    },
  };

  await withServer(rpc, async (baseUrl) => {
    const first = fetch(`${baseUrl}/turn`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "first" }),
    });
    await started.promise;

    const reset = await fetch(`${baseUrl}/new_session`, { method: "POST" });
    assert.equal(reset.status, 200);
    assert.equal(abortCalls, 1);
    assert.equal(resetCalls, 1);
    assert.equal(await (await first).text(), "");
  });
});

test("the RPC lock is released after a failed turn", async () => {
  let calls = 0;
  const rpc = {
    async health() {},
    async newSession() {},
    async turn(_message, onText) {
      calls += 1;
      if (calls === 1) throw new Error("failed");
      onText("ok");
    },
  };

  await withServer(rpc, async (baseUrl) => {
    const first = await fetch(`${baseUrl}/turn`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "first" }),
    });
    assert.equal(first.status, 200);

    const second = await fetch(`${baseUrl}/turn`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "second" }),
    });
    assert.equal(second.status, 200);
    assert.equal(await second.text(), "ok");
  });
});

test("health returns 500 when the pi process is unavailable", async () => {
  const rpc = {
    async health() { throw new Error("pi process is not running"); },
    async newSession() {},
    async turn() {},
  };
  await withServer(rpc, async (baseUrl) => {
    const response = await fetch(`${baseUrl}/health`);
    assert.equal(response.status, 500);
    assert.match(await response.text(), /pi process is not running/);
  });
});
