import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  effectiveRuntimeEnv,
  loadRuntimeConfig,
  runtimeConfigFingerprint,
} from "../runtime-config.mjs";

test("runtime config overrides env and ignores unknown keys", () => {
  const dir = mkdtempSync(join(tmpdir(), "dotty-pi-runtime-"));
  const path = join(dir, "runtime-config.json");
  writeFileSync(path, JSON.stringify({
    DOTTY_PI_MODEL: "persisted-model",
    DOTTY_PI_SIMPLE_REASONING: "true",
    DOTTY_ADMIN_TOKEN: "not-readable",
  }));
  try {
    const env = { DOTTY_RUNTIME_CONFIG_FILE: path, DOTTY_PI_MODEL: "env-model" };
    assert.deepEqual(loadRuntimeConfig(env), {
      DOTTY_PI_MODEL: "persisted-model",
      DOTTY_PI_SIMPLE_REASONING: "true",
    });
    assert.equal(effectiveRuntimeEnv(env).DOTTY_PI_MODEL, "persisted-model");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runtime config fingerprint changes with model settings", () => {
  const dir = mkdtempSync(join(tmpdir(), "dotty-pi-runtime-"));
  const path = join(dir, "runtime-config.json");
  const env = { DOTTY_RUNTIME_CONFIG_FILE: path, DOTTY_PI_MODEL: "one" };
  try {
    const before = runtimeConfigFingerprint(env);
    writeFileSync(path, JSON.stringify({ DOTTY_PI_MODEL: "two" }));
    assert.notEqual(runtimeConfigFingerprint(env), before);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("missing or invalid runtime config is ignored", () => {
  assert.deepEqual(loadRuntimeConfig({ DOTTY_RUNTIME_CONFIG_FILE: "/missing" }), {});
});
