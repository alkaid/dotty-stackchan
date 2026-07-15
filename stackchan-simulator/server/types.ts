export type ServiceName = "behaviour" | "bridge" | "xiaozhi" | "dotty-pi";
export type Risk = "safe" | "mutating" | "cost" | "hardware";

export interface ApiParameter {
  name: string;
  in: "path" | "query" | "header";
  required?: boolean;
  schema?: Record<string, unknown>;
  description?: string;
}

export interface ApiCard {
  id: string;
  service: ServiceName;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  summary: string;
  risk: Risk;
  smoke: boolean;
  contentType?: "json" | "multipart";
  parameters?: ApiParameter[];
  bodySchema?: Record<string, unknown>;
  defaultBody?: unknown;
  stream?: boolean;
}

export interface DriftItem {
  service: ServiceName;
  method: string;
  path: string;
  kind: "missing-card" | "missing-upstream" | "unavailable";
}

export interface DeviceState {
  connected: boolean;
  deviceId: string;
  sessionId: string;
  status: "offline" | "idle" | "listening" | "thinking" | "speaking";
  emotion: string;
  subtitle: string;
  mouth: number;
  yaw: number;
  pitch: number;
  speed: number;
  volume: number;
  mode: string;
  kidMode: boolean;
  smartMode: boolean;
  leds: string[];
}

export interface LogEntry {
  id: number;
  ts: string;
  direction: "in" | "out" | "local";
  service: string;
  deviceId: string;
  kind: "HTTP" | "WS" | "MCP" | "AUDIO" | "SYSTEM";
  summary: string;
  payload?: unknown;
  binaryLength?: number;
  durationMs?: number;
}
