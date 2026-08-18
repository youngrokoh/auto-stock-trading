import { describe, expect, it } from "vitest";

import { parseEtfDetail, parseEtfs } from "../src/lib/etf";

const snapshotPayload = {
  as_of: "2026-08-18T01:00:00Z",
  change_percent: "0.00",
  currency: "KRW",
  divergence_rate: "-0.28",
  index_name: "KOSPI200",
  listed_shares: 236150000,
  listing_date: "2002-10-14",
  manager: "삼성자산운용(ETF)",
  nav: "110371.90",
  net_asset_total: 260643,
  previous_volume: 17088038,
  price: "110060",
  received_at: "2026-08-18T01:00:00Z",
  tracking_error: "0.39",
  tracking_multiple: "1.00",
  volume: 495,
};

describe("etf schemas", () => {
  it("ETF 목록 계약을 단위·스냅샷과 함께 수용한다", () => {
    const parsed = parseEtfs({
      etfs: [
        {
          isin: "KR70000H0005",
          name: "KODEX 인도Nifty미드캡100",
          snapshot: null,
          symbol: "0000H0",
        },
        { isin: "KR7069500007", name: "KODEX 200", snapshot: snapshotPayload, symbol: "069500" },
      ],
      master_source: "KIS_MASTER",
      net_asset_unit: "hundred_million_krw",
      source: "KIS",
    });
    expect(parsed.etfs).toHaveLength(2);
    expect(parsed.etfs[1]?.snapshot?.divergence_rate).toBe("-0.28");
    expect(parsed.net_asset_unit).toBe("hundred_million_krw");
  });

  it("ETF 상세 계약을 분배율 수식과 함께 수용한다", () => {
    const parsed = parseEtfDetail({
      distribution_yield: {
        distribution_count: 4,
        distribution_total: "708",
        formula: "최근 12개월 주당 분배금 합계 ÷ 현재가 × 100",
        unavailable_reason: null,
        value: "0.64",
        window_end: "2026-08-18",
        window_start: "2025-08-18",
      },
      isin: "KR7069500007",
      master_source: "KIS_MASTER",
      name: "KODEX 200",
      net_asset_unit: "hundred_million_krw",
      snapshot: snapshotPayload,
      source: "KIS",
      symbol: "069500",
    });
    expect(parsed.distribution_yield.value).toBe("0.64");
    expect(parsed.distribution_yield.formula).toContain("12개월");
  });

  it("계약 밖 필드는 거부한다", () => {
    expect(() =>
      parseEtfs({
        etfs: [],
        master_source: "KIS_MASTER",
        net_asset_unit: "hundred_million_krw",
        source: "KIS",
        databaseUrl: "postgresql://x",
      }),
    ).toThrow();
  });
});
