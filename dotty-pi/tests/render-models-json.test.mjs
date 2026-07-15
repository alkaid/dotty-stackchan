import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("models renderer emits the configured split routes using pi's schema", () => {
  const piHome = mkdtempSync(join(tmpdir(), "dotty-models-test-"));
  try {
    const result = spawnSync(
      process.execPath,
      [new URL("../render-models-json.mjs", import.meta.url).pathname],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          PI_HOME: piHome,
          DOTTY_PI_BASE_URL: "https://sub2api.example/v1/",
          DOTTY_PI_API_KEY: "test-key",
          DOTTY_PI_PROVIDER: "sub2api",
          DOTTY_PI_MODEL: "simple-id",
          VOICE_THINKER_MODEL: "think-id",
          DOTTY_PI_THINK_REASONING_EFFORT: "high",
        },
      },
    );
    assert.equal(result.status, 0, result.stderr);
    const config = JSON.parse(
      readFileSync(join(piHome, "agent/models.json"), "utf8"),
    );
    const provider = config.providers.sub2api;
    assert.equal(provider.baseUrl, "https://sub2api.example/v1");
    assert.equal(provider.apiKey, "test-key");
    assert.deepEqual(provider.models.map((model) => model.id), [
      "simple-id", "think-id",
    ]);
    assert.deepEqual(provider.models[1].thinkingLevelMap, { high: "high" });
    assert.equal("reasoningEffort" in provider.models[1], false);
  } finally {
    rmSync(piHome, { recursive: true, force: true });
  }
});

test("models renderer prefers persisted runtime model settings", () => {
  const piHome = mkdtempSync(join(tmpdir(), "dotty-models-runtime-test-"));
  const runtimePath = join(piHome, "runtime-config.json");
  writeFileSync(runtimePath, JSON.stringify({
    DOTTY_PI_MODEL: "runtime-simple",
    VOICE_THINKER_MODEL: "runtime-think",
    DOTTY_PI_SIMPLE_REASONING: "true",
    DOTTY_PI_SIMPLE_REASONING_EFFORT: "low",
    DOTTY_PI_THINK_REASONING_EFFORT: "xhigh",
  }));
  try {
    const result = spawnSync(
      process.execPath,
      [new URL("../render-models-json.mjs", import.meta.url).pathname],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          PI_HOME: piHome,
          DOTTY_RUNTIME_CONFIG_FILE: runtimePath,
          DOTTY_PI_MODEL: "env-simple",
          VOICE_THINKER_MODEL: "env-think",
        },
      },
    );
    assert.equal(result.status, 0, result.stderr);
    const config = JSON.parse(
      readFileSync(join(piHome, "agent/models.json"), "utf8"),
    );
    const models = Object.values(config.providers)[0].models;
    assert.deepEqual(models.map((model) => model.id), [
      "runtime-simple", "runtime-think",
    ]);
    assert.deepEqual(models[0].thinkingLevelMap, { low: "low" });
    assert.deepEqual(models[1].thinkingLevelMap, { xhigh: "xhigh" });
  } finally {
    rmSync(piHome, { recursive: true, force: true });
  }
});
