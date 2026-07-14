// think_hard equivalence + behaviour tests.
//
// Split into three groups:
//   1. Request-body shape vs Python oracle (deterministic).
//   2. Wrapper behaviour with mocked fetch (success / timeout / error).
//   3. Optional live smoke test against an OpenAI-compatible thinker,
//      gated by DOTTY_THINKER_URL.

import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { buildThinkRequest, runThinkHard } from "../src/tools/think_hard.ts";
import { TimeoutError } from "../src/lib/llama_swap.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ORACLE = join(__dirname, "think_hard_oracle.py");

let failures = 0;

function assertEq(label: string, actual: unknown, expected: unknown): void {
  const a = typeof actual === "string" ? actual : JSON.stringify(actual);
  const e = typeof expected === "string" ? expected : JSON.stringify(expected);
  if (a === e) {
    process.stdout.write(`  PASS  ${label}\n`);
    return;
  }
  process.stderr.write(
    `  FAIL  ${label}\n        expected: ${e.slice(0, 240)}\n        actual:   ${a.slice(0, 240)}\n`,
  );
  failures++;
}

function callOracle(question: string): unknown {
  const out = execFileSync("python3", [ORACLE, question], { encoding: "utf8" });
  return JSON.parse(out.trim());
}

// --- 1. Request-body shape -----------------------------------------------

function testRequestBodies(): void {
  process.stdout.write("Request body vs Python oracle:\n");
  const questions = [
    "What is 2+2?",
    "Capital of Australia.",
    "Tell me about the territorial dispute over Taiwan.",
    "", // even empty produces a valid body; the wrapper short-circuits before the call
  ];
  for (const q of questions) {
    const expected = callOracle(q);
    const actual = buildThinkRequest(q);
    assertEq(`buildThinkRequest(${JSON.stringify(q)})`, actual, expected);
  }
}

// --- 2. Wrapper behaviour with mocked fetch ------------------------------

interface FetchMock {
  status?: number;
  json?: unknown;
  throws?: Error;
  calls?: Array<{ url: string; init: RequestInit }>;
}

function installFetchMock(mock: FetchMock): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = (async (url: any, init: any) => {
    mock.calls?.push({ url: String(url), init: init as RequestInit });
    if (mock.throws) throw mock.throws;
    return {
      ok: (mock.status ?? 200) >= 200 && (mock.status ?? 200) < 300,
      status: mock.status ?? 200,
      async json() {
        return mock.json;
      },
    } as Response;
  }) as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

async function testEmptyInput(): Promise<void> {
  process.stdout.write("\nEmpty / whitespace input short-circuits:\n");
  for (const q of ["", "   ", "\n\t"]) {
    const got = await runThinkHard(q);
    assertEq(`runThinkHard(${JSON.stringify(q)})`, got, "(empty question)");
  }
}

async function testSuccess(): Promise<void> {
  process.stdout.write("\nSuccess path:\n");
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const restore = installFetchMock({
    json: { choices: [{ message: { content: "  Pong.  " } }] },
    calls,
  });
  try {
    const got = await runThinkHard("What is the answer?", {
      url: "https://sub2api.example.test/v1/chat/completions",
      apiKey: "test-key",
    });
    assertEq("trims whitespace", got, "Pong.");
    assertEq("passes bearer token", calls[0].init.headers, {
      "content-type": "application/json",
      authorization: "Bearer test-key",
    });
  } finally {
    restore();
  }
}

async function testSub2ApiKeyFallback(): Promise<void> {
  process.stdout.write("\nDOTTY_PI_API_KEY fallback:\n");
  const originalVoiceKey = process.env.VOICE_THINKER_API_KEY;
  const originalSub2ApiKey = process.env.DOTTY_PI_API_KEY;
  process.env.VOICE_THINKER_API_KEY = "";
  process.env.DOTTY_PI_API_KEY = "fallback-key";
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const restore = installFetchMock({
    json: { choices: [{ message: { content: "Ok." } }] },
    calls,
  });
  try {
    await runThinkHard("Q?", {
      url: "https://sub2api.example.test/v1/chat/completions",
    });
    assertEq("falls back to DOTTY_PI_API_KEY", calls[0].init.headers, {
      "content-type": "application/json",
      authorization: "Bearer fallback-key",
    });
  } finally {
    restore();
    if (originalVoiceKey === undefined) {
      delete process.env.VOICE_THINKER_API_KEY;
    } else {
      process.env.VOICE_THINKER_API_KEY = originalVoiceKey;
    }
    if (originalSub2ApiKey === undefined) {
      delete process.env.DOTTY_PI_API_KEY;
    } else {
      process.env.DOTTY_PI_API_KEY = originalSub2ApiKey;
    }
  }
}

async function testBaseUrlFallback(): Promise<void> {
  process.stdout.write("\nDOTTY_PI_BASE_URL fallback:\n");
  const originalThinkerUrl = process.env.VOICE_THINKER_URL;
  const originalBaseUrl = process.env.DOTTY_PI_BASE_URL;
  process.env.VOICE_THINKER_URL = "";
  process.env.DOTTY_PI_BASE_URL = "https://sub2api.example.test/v1/";
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const restore = installFetchMock({
    json: { choices: [{ message: { content: "Ok." } }] },
    calls,
  });
  try {
    await runThinkHard("Q?");
    assertEq(
      "derives chat-completions URL",
      calls[0].url,
      "https://sub2api.example.test/v1/chat/completions",
    );
  } finally {
    restore();
    if (originalThinkerUrl === undefined) delete process.env.VOICE_THINKER_URL;
    else process.env.VOICE_THINKER_URL = originalThinkerUrl;
    if (originalBaseUrl === undefined) delete process.env.DOTTY_PI_BASE_URL;
    else process.env.DOTTY_PI_BASE_URL = originalBaseUrl;
  }
}

function testReasoningOverrides(): void {
  process.stdout.write("\nReasoning configuration:\n");
  const originalReasoning = process.env.DOTTY_PI_THINK_REASONING;
  const originalEffort = process.env.DOTTY_PI_THINK_REASONING_EFFORT;
  const originalMaxTokens = process.env.DOTTY_PI_THINK_MAX_TOKENS;
  process.env.DOTTY_PI_THINK_REASONING = "false";
  process.env.DOTTY_PI_THINK_REASONING_EFFORT = "medium";
  process.env.DOTTY_PI_THINK_MAX_TOKENS = "1234";
  try {
    const body = buildThinkRequest("Q?");
    assertEq("enable_thinking", body.chat_template_kwargs, { enable_thinking: false });
    assertEq("reasoning_effort", body.reasoning_effort, "medium");
    assertEq("max_tokens", body.max_tokens, 1234);
  } finally {
    if (originalReasoning === undefined) delete process.env.DOTTY_PI_THINK_REASONING;
    else process.env.DOTTY_PI_THINK_REASONING = originalReasoning;
    if (originalEffort === undefined) delete process.env.DOTTY_PI_THINK_REASONING_EFFORT;
    else process.env.DOTTY_PI_THINK_REASONING_EFFORT = originalEffort;
    if (originalMaxTokens === undefined) delete process.env.DOTTY_PI_THINK_MAX_TOKENS;
    else process.env.DOTTY_PI_THINK_MAX_TOKENS = originalMaxTokens;
  }
}

async function testLongResponseCap(): Promise<void> {
  process.stdout.write("\n500-char output cap:\n");
  const restore = installFetchMock({
    json: { choices: [{ message: { content: "a".repeat(600) } }] },
  });
  try {
    const got = await runThinkHard("Q?");
    assertEq("length", got.length, 500);
    assertEq("contents", got, "a".repeat(500));
  } finally {
    restore();
  }
}

async function testTimeout(): Promise<void> {
  process.stdout.write("\nTimeout fallback:\n");
  const restore = installFetchMock({ throws: new TimeoutError("test") });
  try {
    const got = await runThinkHard("Q?");
    assertEq(
      "timeout reply",
      got,
      "(I'm slow today, try again in a moment)",
    );
  } finally {
    restore();
  }
}

async function testGenericError(): Promise<void> {
  process.stdout.write("\nGeneric error fallback:\n");
  const restore = installFetchMock({ throws: new Error("ECONNREFUSED") });
  try {
    const got = await runThinkHard("Q?");
    assertEq("generic-error reply", got, "(thinking failed)");
  } finally {
    restore();
  }
}

async function testHttpError(): Promise<void> {
  process.stdout.write("\nNon-2xx HTTP response → generic-error fallback:\n");
  const restore = installFetchMock({ status: 503, json: { error: "busy" } });
  try {
    const got = await runThinkHard("Q?");
    assertEq("http-503 reply", got, "(thinking failed)");
  } finally {
    restore();
  }
}

// --- 3. Optional live smoke test ----------------------------------------

async function testLiveSmoke(): Promise<void> {
  const url = process.env.DOTTY_THINKER_URL;
  if (!url) {
    process.stdout.write(
      "\nLive smoke: SKIPPED (set DOTTY_THINKER_URL=https://DOTTY_PI_BASE_URL_PLACEHOLDER/v1/chat/completions to run).\n",
    );
    return;
  }
  process.stdout.write(`\nLive smoke against ${url}:\n`);
  const got = await runThinkHard("Reply with exactly the word: pong", {
    url,
    timeoutSec: 60,
  });
  const ok = got.length > 0 && got.length <= 500 && !got.startsWith("(");
  if (ok) {
    process.stdout.write(`  PASS  got non-empty bounded reply: ${JSON.stringify(got.slice(0, 120))}\n`);
  } else {
    process.stderr.write(`  FAIL  unexpected reply: ${JSON.stringify(got)}\n`);
    failures++;
  }
}

async function main(): Promise<void> {
  testRequestBodies();
  await testEmptyInput();
  await testSuccess();
  await testSub2ApiKeyFallback();
  await testBaseUrlFallback();
  testReasoningOverrides();
  await testLongResponseCap();
  await testTimeout();
  await testGenericError();
  await testHttpError();
  await testLiveSmoke();

  process.stdout.write(`\n${failures === 0 ? "OK" : "FAIL"} — ${failures} failure(s)\n`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
