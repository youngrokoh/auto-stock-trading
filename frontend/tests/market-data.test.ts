import { describe, expect, it } from "vitest";

import { formatDecimal, formatKstDateTime, formatSignedPercent } from "../src/lib/format";
import {
  parseCorporateActions,
  parseDailyBars,
  parseInstruments,
  parseQuote,
} from "../src/lib/market-data";

const instrumentPayload = {
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
};

describe("market data schemas", () => {
  it("종목 목록 계약을 그대로 수용한다", () => {
    const parsed = parseInstruments({ instruments: [instrumentPayload] });
    expect(parsed.instruments[0]?.symbol).toBe("069500");
  });

  it("계약 밖 필드는 거부한다", () => {
    expect(() =>
      parseInstruments({
        instruments: [{ ...instrumentPayload, databaseUrl: "postgresql://x" }],
      }),
    ).toThrow();
  });

  it("현재가와 일봉 계약을 수용한다", () => {
    const quote = parseQuote({
      as_of: "2026-08-14T06:35:00Z",
      change: "500",
      change_percent: "0.68",
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
    });
    expect(quote.price).toBe("110060");

    const bars = parseDailyBars({
      bars: [
        {
          adjusted: false,
          close_price: "110060.00000000",
          confirmed_at: "2026-08-17T02:00:00Z",
          correction_code: null,
          finality: "confirmed",
          high_price: "110800.00000000",
          low_price: "108145.00000000",
          open_price: "110220.00000000",
          received_at: "2026-08-14T06:35:00Z",
          source: "KIS",
          split_ratio: "0E-8",
          trading_date: "2026-08-14",
          trading_value: "1871747637027.00000000",
          valid_from: "2026-08-14T06:35:00Z",
          version: 1,
          volume: 17088038,
        },
      ],
      end_date: null,
      interval: "1d",
      source: "KIS",
      start_date: null,
      symbol: "069500",
    });
    expect(bars.bars[0]?.finality).toBe("confirmed");
  });

  it("기업행사 계약을 수용한다", () => {
    const parsed = parseCorporateActions({
      actions: [
        {
          action_key: "cff22f82-fc6b-46b1-b28a-98499f46c673",
          action_type: "etf_distribution",
          announced_at: null,
          announcement_date: "2026-08-17",
          available_at: "2026-08-17T02:26:53Z",
          cash_amount: "183.00000000",
          corporate_action_id: "ae0e3221-22cb-45d6-a6d8-3b8d32206323",
          currency: "KRW",
          effective_date: null,
          ex_date: "2026-07-30",
          lifecycle: "confirmed",
          payment_date: null,
          quality: "verified",
          received_at: "2026-08-17T02:26:53Z",
          record_date: "2026-07-31",
          related_instrument_id: null,
          share_multiplier: null,
          source: "KODEX",
          source_event_id: "2ETF01:20260731",
          source_reference: "https://example.test",
          subscription_price: null,
          superseded_at: null,
          time_precision: "date",
          valid_from: "2026-08-17T02:26:53Z",
          version: 2,
        },
      ],
      end_date: null,
      include_history: false,
      knowledge_cutoff_at: null,
      start_date: null,
      symbol: "069500",
    });
    expect(parsed.actions[0]?.quality).toBe("verified");
  });
});

describe("format helpers", () => {
  it("소수 문자열을 불필요한 0 없이 천 단위로 표기한다", () => {
    expect(formatDecimal("110060.00000000")).toBe("110,060");
    expect(formatDecimal("0.68")).toBe("0.68");
    expect(formatDecimal("1871747637027.00000000")).toBe("1,871,747,637,027");
  });

  it("부호 있는 백분율을 표기한다", () => {
    expect(formatSignedPercent("0.68")).toBe("+0.68%");
    expect(formatSignedPercent("-1.20")).toBe("-1.2%");
    expect(formatSignedPercent("0")).toBe("0%");
  });

  it("UTC 시각을 서울 기준으로 표기한다", () => {
    expect(formatKstDateTime("2026-08-14T06:35:00Z")).toBe("2026-08-14 15:35");
  });
});
