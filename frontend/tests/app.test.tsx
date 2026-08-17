import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/App";

afterEach(() => {
  vi.unstubAllGlobals();
});

const jsonResponse = (payload: unknown): Response =>
  new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status: 200,
  });

const stubApi = () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/health/status")) {
        return Promise.resolve(
          jsonResponse({
            components: [
              { name: "PostgreSQL", status: "ok" },
              { name: "Valkey", status: "ok" },
            ],
            environment: "development",
            service: "api",
            status: "ready",
            version: "0.1.0",
          }),
        );
      }
      if (url.endsWith("/api/market-data/instruments")) {
        return Promise.resolve(
          jsonResponse({
            instruments: [
              {
                country: "KR",
                currency: "KRW",
                delisted_on: null,
                english_name: null,
                exchange: "XKRX",
                listed_on: null,
                name: "KODEX 200",
                product_type: "etf",
                source: "KIS",
                source_as_of: "2026-08-14",
                symbol: "069500",
                trading_status: "active",
              },
            ],
          }),
        );
      }
      if (url.includes("/quote")) {
        return Promise.resolve(
          jsonResponse({
            as_of: "2026-08-14T06:35:00Z",
            change: "500",
            change_percent: "0.46",
            currency: "KRW",
            high_price: "110800",
            low_price: "108145",
            open_price: "110220",
            previous_close: "109560",
            price: "110060",
            received_at: "2026-08-14T06:35:00Z",
            source: "KIS",
            symbol: "069500",
            trading_value: "1871747637027",
            volume: 17088038,
          }),
        );
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    }),
  );
};

describe("App", () => {
  it("운영 개요가 실제 서비스 상태와 실전거래 안전 경계를 보여준다", async () => {
    stubApi();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(<App queryClient={queryClient} />);

    expect(await screen.findByRole("heading", { name: "운영 개요" })).toBeInTheDocument();
    expect(await screen.findByText("실전거래 비활성")).toBeInTheDocument();
    expect(await screen.findByText("A2 · PostgreSQL")).toBeInTheDocument();
    expect(await screen.findByText("A3 · Valkey")).toBeInTheDocument();
    expect(await screen.findByText("KODEX 200 069500")).toBeInTheDocument();
    expect(await screen.findByText("110,060")).toBeInTheDocument();
    expect(
      screen.getByText("운영 이벤트 스트림은 아직 만들지 않았습니다.", { exact: false }),
    ).toBeInTheDocument();
  });
});
