#!/usr/bin/env node
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { effectiveRuntimeEnv } from "./runtime-config.mjs";

const runtimeEnv = effectiveRuntimeEnv();

function env(name, fallback = "") {
  const value = runtimeEnv[name];
  return value === undefined || value === "" ? fallback : value;
}

function boolEnv(name, fallback) {
  const value = env(name, String(fallback)).toLowerCase();
  return ["1", "true", "yes", "on"].includes(value);
}

function intEnv(name, fallback) {
  const raw = env(name, String(fallback));
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer, got ${JSON.stringify(raw)}`);
  }
  return parsed;
}

const THINKING_LEVELS = new Set([
  "off", "minimal", "low", "medium", "high", "xhigh",
]);

function modelConfig(prefix, defaults, options = {}) {
  const id = options.modelIdEnv
    ? env(options.modelIdEnv, defaults.id)
    : env(`${prefix}_MODEL_ID`, defaults.id);
  const model = {
    id,
    name: env(`${prefix}_MODEL_NAME`, defaults.name),
    reasoning: boolEnv(`${prefix}_REASONING`, defaults.reasoning),
    input: ["text"],
    contextWindow: intEnv(`${prefix}_CONTEXT_WINDOW`, defaults.contextWindow),
    maxTokens: intEnv(`${prefix}_MAX_TOKENS`, defaults.maxTokens),
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  };
  const effort = env(`${prefix}_REASONING_EFFORT`).toLowerCase();
  if (effort) {
    if (!THINKING_LEVELS.has(effort)) {
      throw new Error(
        `${prefix}_REASONING_EFFORT must be a pi thinking level, got ${JSON.stringify(effort)}`,
      );
    }
    model.thinkingLevelMap = { [effort]: effort };
  }
  return model;
}

const providerId = env("DOTTY_PI_PROVIDER", "sub2api");
const baseUrl = env(
  "DOTTY_PI_BASE_URL",
  "https://DOTTY_PI_BASE_URL_PLACEHOLDER/v1",
).replace(/\/+$/, "");
const apiKey = env("DOTTY_PI_API_KEY", "DOTTY_PI_API_KEY_PLACEHOLDER");

const simpleDefaults = {
  id: "dotty-simple",
  name: "Dotty simple route (sub2api)",
  reasoning: false,
  contextWindow: 128000,
  maxTokens: 2048,
};
const thinkDefaults = {
  id: "dotty-think",
  name: "Dotty think_hard route (sub2api)",
  reasoning: true,
  contextWindow: 128000,
  maxTokens: 4096,
};

const config = {
  providers: {
    [providerId]: {
      baseUrl,
      api: env("DOTTY_PI_PROVIDER_API", "openai-completions"),
      apiKey,
      compat: {
        supportsDeveloperRole: boolEnv("DOTTY_PI_SUPPORTS_DEVELOPER_ROLE", false),
        supportsReasoningEffort: boolEnv("DOTTY_PI_SUPPORTS_REASONING_EFFORT", true),
      },
      models: [
        modelConfig("DOTTY_PI_SIMPLE", simpleDefaults, { modelIdEnv: "DOTTY_PI_MODEL" }),
        modelConfig("DOTTY_PI_THINK", thinkDefaults, { modelIdEnv: "VOICE_THINKER_MODEL" }),
      ],
    },
  },
};

const piHome = env("PI_HOME", "/root/.pi");
const outputPath = join(piHome, "agent", "models.json");
mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(config, null, 2)}\n`);
console.log(`rendered ${outputPath} provider=${providerId} baseUrl=${baseUrl}`);
