import type { ApiCard, DriftItem, ServiceName } from "./types.js";

export function resolveServiceBases(env: NodeJS.ProcessEnv = process.env): Record<ServiceName, string> {
  return {
    behaviour: env.DOTTY_BEHAVIOUR_URL || `http://127.0.0.1:${env.DOTTY_BEHAVIOUR_PORT || "8090"}`,
    bridge: env.DOTTY_BRIDGE_URL || `http://127.0.0.1:${env.DOTTY_BRIDGE_PORT || "8081"}`,
    xiaozhi: env.XIAOZHI_HTTP_URL || `http://127.0.0.1:${env.XIAOZHI_HTTP_PORT || "8003"}`,
    "dotty-pi": env.DOTTY_PI_URL || `http://127.0.0.1:${env.DOTTY_PI_RPC_PORT || "8091"}`,
  };
}

export const SERVICE_BASES = resolveServiceBases();

const p = (name: string, where: "path" | "query" | "header", required = false) => ({
  name, in: where, required, schema: { type: "string" },
});

export const DECLARED_CATALOG: ApiCard[] = [
  { id: "behaviour-health", service: "behaviour", method: "GET", path: "/health", summary: "Behaviour liveness", risk: "safe", smoke: true },
  { id: "behaviour-event", service: "behaviour", method: "POST", path: "/api/perception/event", summary: "Publish perception event", risk: "mutating", smoke: false, defaultBody: { device_id: "stackchan-sim-001", name: "face_detected", data: {} } },
  { id: "behaviour-state", service: "behaviour", method: "GET", path: "/api/perception/state", summary: "Per-device perception state", risk: "safe", smoke: true, parameters: [p("device_id", "query")] },
  { id: "behaviour-recent", service: "behaviour", method: "GET", path: "/api/perception/recent/{device_id}", summary: "Recent device events", risk: "safe", smoke: true, parameters: [p("device_id", "path", true), p("limit", "query")] },
  { id: "behaviour-sound", service: "behaviour", method: "GET", path: "/api/perception/sound-balance/{device_id}", summary: "Sound direction balance", risk: "safe", smoke: true, parameters: [p("device_id", "path", true)] },
  { id: "behaviour-feed", service: "behaviour", method: "GET", path: "/api/perception/feed", summary: "Perception SSE feed", risk: "safe", smoke: false, stream: true },
  { id: "behaviour-vision-explain", service: "behaviour", method: "POST", path: "/api/vision/explain", summary: "Describe an uploaded image", risk: "cost", smoke: false, contentType: "multipart", parameters: [p("Device-Id", "header")], defaultBody: { question: "What do you see?" } },
  { id: "behaviour-vision-cache", service: "behaviour", method: "GET", path: "/api/vision/cache", summary: "Vision result cache", risk: "safe", smoke: true },
  { id: "behaviour-vision-photo", service: "behaviour", method: "GET", path: "/api/vision/photo/{device_id}", summary: "Latest cached device photo", risk: "safe", smoke: false, parameters: [p("device_id", "path", true)] },
  { id: "behaviour-vision-latest", service: "behaviour", method: "GET", path: "/api/vision/latest/{device_id}", summary: "Wait for a fresh vision result", risk: "safe", smoke: false, parameters: [p("device_id", "path", true), p("after", "query"), p("timeout", "query")] },
  { id: "behaviour-audio-explain", service: "behaviour", method: "POST", path: "/api/audio/explain", summary: "Explain an uploaded audio clip", risk: "cost", smoke: false, contentType: "multipart", parameters: [p("Device-Id", "header")], defaultBody: { question: "Describe what you hear." } },
  { id: "behaviour-audio-cache", service: "behaviour", method: "GET", path: "/api/audio/cache", summary: "Audio result cache", risk: "safe", smoke: true },
  { id: "behaviour-calendar", service: "behaviour", method: "GET", path: "/api/calendar/today", summary: "Today's calendar context", risk: "safe", smoke: true, parameters: [p("person", "query")] },
  { id: "behaviour-scene", service: "behaviour", method: "GET", path: "/api/scene-synthesis/recent", summary: "Recent scene synthesis", risk: "safe", smoke: true, parameters: [p("device_id", "query")] },
  { id: "behaviour-voice-photo", service: "behaviour", method: "GET", path: "/api/voice/take_photo", summary: "Read latest voice photo description", risk: "safe", smoke: true },
  { id: "behaviour-review", service: "behaviour", method: "GET", path: "/api/voice/person_review_status", summary: "Person memory review gate", risk: "safe", smoke: false, parameters: [p("person_id", "query", true)] },

  { id: "bridge-health", service: "bridge", method: "GET", path: "/health", summary: "Dashboard liveness", risk: "safe", smoke: true },
  { id: "bridge-kid", service: "bridge", method: "POST", path: "/admin/kid-mode", summary: "Set kid mode", risk: "mutating", smoke: false, defaultBody: { enabled: true, device_id: "stackchan-sim-001" } },
  { id: "bridge-smart", service: "bridge", method: "POST", path: "/admin/smart-mode", summary: "Set smart mode", risk: "mutating", smoke: false, defaultBody: { enabled: false, device_id: "stackchan-sim-001" } },
  { id: "bridge-state", service: "bridge", method: "POST", path: "/admin/state", summary: "Set robot state", risk: "hardware", smoke: false, defaultBody: { state: "idle", device_id: "stackchan-sim-001" } },

  { id: "xiaozhi-ota-get", service: "xiaozhi", method: "GET", path: "/xiaozhi/ota/", summary: "Read OTA configuration", risk: "safe", smoke: true },
  { id: "xiaozhi-ota-post", service: "xiaozhi", method: "POST", path: "/xiaozhi/ota/", summary: "Negotiate OTA configuration", risk: "safe", smoke: false, defaultBody: {} },
  { id: "xiaozhi-vision-get", service: "xiaozhi", method: "GET", path: "/mcp/vision/explain", summary: "Xiaozhi vision probe", risk: "safe", smoke: false },
  { id: "xiaozhi-vision-post", service: "xiaozhi", method: "POST", path: "/mcp/vision/explain", summary: "Xiaozhi vision request", risk: "cost", smoke: false, contentType: "multipart", defaultBody: { question: "What do you see?" } },
  { id: "xiaozhi-inject", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/inject-text", summary: "Inject a chat turn", risk: "cost", smoke: false, defaultBody: { text: "Hello", device_id: "stackchan-sim-001" } },
  { id: "xiaozhi-devices", service: "xiaozhi", method: "GET", path: "/xiaozhi/admin/devices", summary: "Connected device IDs", risk: "safe", smoke: true },
  { id: "xiaozhi-abort", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/abort", summary: "Abort current turn", risk: "mutating", smoke: false, defaultBody: { device_id: "stackchan-sim-001" } },
  { id: "xiaozhi-head", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/set-head-angles", summary: "Move simulated head", risk: "hardware", smoke: false, defaultBody: { device_id: "stackchan-sim-001", yaw: 0, pitch: 45, speed: 250 } },
  { id: "xiaozhi-state", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/set-state", summary: "Set simulated state", risk: "hardware", smoke: false, defaultBody: { device_id: "stackchan-sim-001", state: "idle" } },
  { id: "xiaozhi-toggle", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/set-toggle", summary: "Set simulated toggle", risk: "hardware", smoke: false, defaultBody: { device_id: "stackchan-sim-001", name: "kid_mode", enabled: true } },
  { id: "xiaozhi-face", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/set-face-identified", summary: "Signal face identification", risk: "hardware", smoke: false, defaultBody: { device_id: "stackchan-sim-001" } },
  { id: "xiaozhi-photo", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/take-photo", summary: "Request simulated photo", risk: "cost", smoke: false, defaultBody: { device_id: "stackchan-sim-001", question: "What do you see?" } },
  { id: "xiaozhi-capture", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/capture-audio", summary: "Request simulated audio clip", risk: "cost", smoke: false, defaultBody: { device_id: "stackchan-sim-001", duration_ms: 4000 } },
  { id: "xiaozhi-play", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/play-asset", summary: "Play server-side asset", risk: "hardware", smoke: false, defaultBody: { device_id: "stackchan-sim-001", asset: "/opt/xiaozhi-esp32-server/config/assets/purr.opus" } },
  { id: "xiaozhi-songs", service: "xiaozhi", method: "GET", path: "/xiaozhi/admin/songs", summary: "List server-side songs", risk: "safe", smoke: true },
  { id: "xiaozhi-say", service: "xiaozhi", method: "POST", path: "/xiaozhi/admin/say", summary: "Speak text on device", risk: "hardware", smoke: false, defaultBody: { device_id: "stackchan-sim-001", text: "Hello from the simulator" } },

  { id: "pi-health", service: "dotty-pi", method: "GET", path: "/health", summary: "Pi RPC liveness", risk: "safe", smoke: true },
  { id: "pi-session", service: "dotty-pi", method: "POST", path: "/new_session", summary: "Reset Pi session", risk: "mutating", smoke: false, defaultBody: {} },
  { id: "pi-turn", service: "dotty-pi", method: "POST", path: "/turn", summary: "Stream a Pi agent turn", risk: "cost", smoke: false, stream: true, defaultBody: { message: "Hello" } },
];

type OpenApiDoc = { paths?: Record<string, Record<string, any>> };
const EXCLUDED = /^(\/docs|\/redoc|\/openapi\.json|\/ui(?:\/|$)|\/favicon|\/manifest)/;

function key(method: string, path: string): string { return `${method.toUpperCase()} ${path}`; }

async function fetchOpenApi(service: "behaviour" | "bridge"): Promise<OpenApiDoc> {
  const response = await fetch(`${SERVICE_BASES[service]}/openapi.json`, {
    signal: AbortSignal.timeout(2500),
  });
  if (!response.ok) throw new Error(`OpenAPI HTTP ${response.status}`);
  return response.json() as Promise<OpenApiDoc>;
}

export async function buildCatalog(): Promise<{ cards: ApiCard[]; drift: DriftItem[] }> {
  const cards = structuredClone(DECLARED_CATALOG);
  const drift: DriftItem[] = [];
  for (const service of ["behaviour", "bridge"] as const) {
    try {
      const doc = await fetchOpenApi(service);
      const upstream = new Map<string, any>();
      for (const [path, operations] of Object.entries(doc.paths || {})) {
        if (EXCLUDED.test(path)) continue;
        for (const [method, operation] of Object.entries(operations)) {
          if (!["get", "post", "put", "patch", "delete"].includes(method)) continue;
          upstream.set(key(method, path), operation);
        }
      }
      const declared = cards.filter((card) => card.service === service);
      for (const card of declared) {
        const operation = upstream.get(key(card.method, card.path));
        if (!operation) {
          drift.push({ service, method: card.method, path: card.path, kind: "missing-upstream" });
          continue;
        }
        card.summary = operation.summary || operation.description?.split("\n")[0] || card.summary;
        card.parameters = operation.parameters || card.parameters;
        card.bodySchema = operation.requestBody?.content?.["application/json"]?.schema || card.bodySchema;
        upstream.delete(key(card.method, card.path));
      }
      for (const missingKey of upstream.keys()) {
        const [method, ...pathParts] = missingKey.split(" ");
        drift.push({ service, method, path: pathParts.join(" "), kind: "missing-card" });
      }
    } catch {
      drift.push({ service, method: "GET", path: "/openapi.json", kind: "unavailable" });
    }
  }
  return { cards, drift };
}
