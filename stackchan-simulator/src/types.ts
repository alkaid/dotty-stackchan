export interface DeviceState {
  connected: boolean; deviceId: string; sessionId: string;
  status: "offline" | "idle" | "listening" | "thinking" | "speaking";
  emotion: string; subtitle: string; mouth: number; yaw: number; pitch: number;
  speed: number; volume: number; mode: string; kidMode: boolean; smartMode: boolean;
  leds: string[];
}
export interface ApiParameter { name: string; in: "path" | "query" | "header"; required?: boolean; description?: string; schema?: Record<string, unknown>; }
export interface ApiCard { id: string; service: string; method: string; path: string; summary: string; risk: string; smoke: boolean; contentType?: string; parameters?: ApiParameter[]; bodySchema?: Record<string, unknown>; defaultBody?: unknown; stream?: boolean; }
export interface LogEntry { id: number; ts: string; direction: string; service: string; deviceId: string; kind: string; summary: string; payload?: unknown; binaryLength?: number; durationMs?: number; }
export interface DriftItem { service: string; method: string; path: string; kind: string; }
