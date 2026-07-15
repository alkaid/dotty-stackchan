import type { LogEntry } from "./types.js";

const SECRET_KEYS = /token|authorization|api[-_]?key|password|secret/i;

export function redact(value: unknown, depth = 0): unknown {
  if (depth > 8) return "[truncated]";
  if (Array.isArray(value)) return value.map((item) => redact(item, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [
      key,
      SECRET_KEYS.test(key) ? "[redacted]" : redact(item, depth + 1),
    ]));
  }
  if (typeof value === "string" && value.length > 4000) {
    return `${value.slice(0, 4000)}...[truncated]`;
  }
  return value;
}

export class LogStore {
  private entries: LogEntry[] = [];
  private nextId = 1;
  private listeners = new Set<(entry: LogEntry) => void>();

  add(entry: Omit<LogEntry, "id" | "ts">): LogEntry {
    const complete: LogEntry = {
      ...entry,
      id: this.nextId++,
      ts: new Date().toISOString(),
      payload: redact(entry.payload),
    };
    this.entries.push(complete);
    if (this.entries.length > 5000) this.entries.splice(0, this.entries.length - 5000);
    for (const listener of this.listeners) listener(complete);
    return complete;
  }

  list(): LogEntry[] { return [...this.entries]; }
  clear(): void { this.entries = []; }
  subscribe(listener: (entry: LogEntry) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
