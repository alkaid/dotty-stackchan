import { readFileSync } from "node:fs";

export const RUNTIME_CONFIG_KEYS = [
  "DOTTY_PI_MODEL",
  "DOTTY_PI_SIMPLE_REASONING",
  "DOTTY_PI_SIMPLE_REASONING_EFFORT",
  "VOICE_THINKER_MODEL",
  "DOTTY_PI_THINK_REASONING_EFFORT",
];

export function loadRuntimeConfig(env = process.env) {
  const path = env.DOTTY_RUNTIME_CONFIG_FILE
    ?? "/var/lib/dotty-bridge/state/runtime-config.json";
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
  return Object.fromEntries(
    RUNTIME_CONFIG_KEYS
      .filter((key) => typeof parsed[key] === "string")
      .map((key) => [key, parsed[key]]),
  );
}

export function effectiveRuntimeEnv(env = process.env) {
  return { ...env, ...loadRuntimeConfig(env) };
}

export function runtimeConfigFingerprint(env = process.env) {
  const effective = effectiveRuntimeEnv(env);
  return JSON.stringify(
    RUNTIME_CONFIG_KEYS.map((key) => [key, effective[key] ?? ""]),
  );
}
