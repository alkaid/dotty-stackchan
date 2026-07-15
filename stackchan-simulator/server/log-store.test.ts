import { describe, expect, it } from "vitest";
import { LogStore, redact } from "./log-store.js";

describe("log store", () => {
  it("redacts nested secrets", () => {
    expect(redact({ headers: { Authorization: "Bearer x", "X-Admin-Token": "secret" }, ok: true })).toEqual({
      headers: { Authorization: "[redacted]", "X-Admin-Token": "[redacted]" }, ok: true,
    });
  });

  it("keeps the newest 5000 entries", () => {
    const store = new LogStore();
    for (let index = 0; index < 5002; index += 1) store.add({ direction: "local", service: "test", deviceId: "sim", kind: "SYSTEM", summary: String(index) });
    expect(store.list()).toHaveLength(5000);
    expect(store.list()[0].summary).toBe("2");
  });
});
