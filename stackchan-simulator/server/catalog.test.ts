import { describe, expect, it } from "vitest";
import { DECLARED_CATALOG, resolveServiceBases } from "./catalog.js";

describe("API catalog", () => {
  it("keeps the 39 machine API baseline", () => {
    expect(DECLARED_CATALOG).toHaveLength(39);
    const counts = DECLARED_CATALOG.reduce<Record<string, typeof DECLARED_CATALOG>>((result, card) => {
      (result[card.service] ||= []).push(card);
      return result;
    }, {});
    expect(counts.behaviour).toHaveLength(16);
    expect(counts.bridge).toHaveLength(4);
    expect(counts.xiaozhi).toHaveLength(16);
    expect(counts["dotty-pi"]).toHaveLength(3);
  });

  it("only marks read-only and no-cost cards for smoke", () => {
    for (const card of DECLARED_CATALOG.filter((item) => item.smoke)) {
      expect(card.risk).toBe("safe");
      expect(card.method).toBe("GET");
    }
  });

  it("uses published host ports outside Compose", () => {
    expect(resolveServiceBases({
      XIAOZHI_HTTP_PORT: "5002",
      DOTTY_BRIDGE_PORT: "5005",
    })).toEqual({
      behaviour: "http://127.0.0.1:8090",
      bridge: "http://127.0.0.1:5005",
      xiaozhi: "http://127.0.0.1:5002",
      "dotty-pi": "http://127.0.0.1:8091",
    });
  });
});
