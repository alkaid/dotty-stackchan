import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { buildPiArgs, createRpcServer, PiRpc } from "../rpc-server.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
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

test("pi starts with the baked persona and no built-in tools", () => {
  const dir = mkdtempSync(join(tmpdir(), "dotty-pi-test-"));
  const promptPath = join(dir, "persona.md");
  writeFileSync(promptPath, "You are Dotty.\n");
  try {
    const args = buildPiArgs({
      DOTTY_PI_SYSTEM_PROMPT_FILE: promptPath,
      DOTTY_PI_PROVIDER: "sub2api",
      DOTTY_PI_MODEL: "dotty-simple",
    });
    assert.ok(args.includes("--no-builtin-tools"));
    assert.equal(args[args.indexOf("--system-prompt") + 1], "You are Dotty.");
    assert.equal(args[args.indexOf("--thinking") + 1], "off");
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

test("health checks do not release an active turn", async () => {
  const started = deferred();
  const release = deferred();
  const rpc = {
    async health() {},
    async newSession() {},
    async turn(_message, onText) {
      started.resolve();
      await release.promise;
      onText("done");
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

    const second = await fetch(`${baseUrl}/turn`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "second" }),
    });
    assert.equal(second.status, 409);

    const reset = await fetch(`${baseUrl}/new_session`, { method: "POST" });
    assert.equal(reset.status, 409);

    release.resolve();
    assert.equal(await (await first).text(), "done");
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
