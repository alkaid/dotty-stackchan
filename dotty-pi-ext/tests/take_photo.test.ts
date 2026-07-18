// take_photo voice tool — thin fetch wrapper, so the test asserts the
// contract against a fake `fetch` rather than running an HTTP server.
//
// Usage:
//   node --experimental-strip-types tests/take_photo.test.ts
//
// Exits non-zero on any assertion failure. No external deps; runs
// without DOTTY_BRAIN_DB_SNAPSHOT or any network access.

import assert from "node:assert/strict";
import { runTakePhoto } from "../src/tools/take_photo.ts";

const FALLBACK = "（现在没有可用的新画面）";

interface FakeFetchInit {
  status?: number;
  body?: unknown;
  throw?: Error;
}

function installFakeFetch(init: FakeFetchInit): () => void {
  const original = globalThis.fetch;
  // deno-lint-ignore no-explicit-any
  (globalThis as any).fetch = async (
    _url: string,
    _opts: RequestInit | undefined,
  ): Promise<Response> => {
    if (init.throw) throw init.throw;
    const body = JSON.stringify(init.body ?? {});
    return new Response(body, {
      status: init.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  return () => {
    // deno-lint-ignore no-explicit-any
    (globalThis as any).fetch = original;
  };
}

async function test200ReturnsDescription() {
  const restore = installFakeFetch({
    body: { description: "A blue chair and a wooden table." },
  });
  try {
    const out = await runTakePhoto();
    assert.equal(out, "A blue chair and a wooden table.");
  } finally {
    restore();
  }
}

async function test200ReturnsFallbackWhenMissingDescription() {
  const restore = installFakeFetch({ body: { description: null } });
  try {
    const out = await runTakePhoto();
    assert.equal(out, FALLBACK);
  } finally {
    restore();
  }
}

async function test200ReturnsFallbackWhenEmptyDescription() {
  const restore = installFakeFetch({ body: { description: "" } });
  try {
    const out = await runTakePhoto();
    assert.equal(out, FALLBACK);
  } finally {
    restore();
  }
}

async function testNon200ReturnsFallback() {
  const restore = installFakeFetch({ status: 500, body: { error: "x" } });
  try {
    const out = await runTakePhoto();
    assert.equal(out, FALLBACK);
  } finally {
    restore();
  }
}

async function testFetchThrowReturnsFallback() {
  const restore = installFakeFetch({ throw: new Error("network down") });
  try {
    const out = await runTakePhoto();
    assert.equal(out, FALLBACK);
  } finally {
    restore();
  }
}

async function main() {
  await test200ReturnsDescription();
  await test200ReturnsFallbackWhenMissingDescription();
  await test200ReturnsFallbackWhenEmptyDescription();
  await testNon200ReturnsFallback();
  await testFetchThrowReturnsFallback();
  console.log("take_photo: 5/5 pass");
}

await main();
