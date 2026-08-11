import { describe, expect, it } from "vitest";

import { parseReadiness } from "../src/lib/health";

describe("parseReadiness", () => {
  it("accepts the public readiness contract", () => {
    const readiness = parseReadiness({
      components: [
        { name: "PostgreSQL", status: "ok" },
        { name: "Valkey", status: "unavailable" },
      ],
      environment: "test",
      service: "api",
      status: "degraded",
      version: "0.1.0",
    });

    expect(readiness.components[1]).toEqual({ name: "Valkey", status: "unavailable" });
  });

  it("rejects fields outside the browser-safe contract", () => {
    expect(() =>
      parseReadiness({
        components: [],
        databaseUrl: "postgresql://secret@example.invalid/database",
        environment: "test",
        service: "api",
        status: "ready",
        version: "0.1.0",
      }),
    ).toThrow();
  });
});
