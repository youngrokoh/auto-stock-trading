import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/App";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("shows real service readiness and the live-trading safety boundary", async () => {
    const response = new Response(
      JSON.stringify({
        components: [
          { name: "PostgreSQL", status: "ok" },
          { name: "Valkey", status: "ok" },
        ],
        environment: "development",
        service: "api",
        status: "ready",
        version: "0.1.0",
      }),
      { headers: { "Content-Type": "application/json" }, status: 200 },
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(response)),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(<App queryClient={queryClient} />);

    expect(await screen.findByRole("heading", { name: "자동매매 운영 현황" })).toBeInTheDocument();
    expect(await screen.findByText("PostgreSQL")).toBeInTheDocument();
    expect(await screen.findByText("Valkey")).toBeInTheDocument();
    expect(screen.getByText("실전거래 비활성")).toBeInTheDocument();
    expect(screen.getByText("가짜 시장 데이터 없이 기반 상태만 표시합니다.")).toBeInTheDocument();
  });
});
