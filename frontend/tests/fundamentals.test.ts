import { describe, expect, it } from "vitest";

import { formatKoreanAmount } from "../src/lib/format";
import { parseFinancialIndicators, parseFinancialReports } from "../src/lib/fundamentals";

const indicatorPayload = {
  category: "growth",
  formula: "(당기 매출액 - 전기 매출액) ÷ |전기 매출액| × 100",
  inputs: [
    {
      account_id: "ifrs-full_Revenue",
      amount: "333605938000000.0000",
      name: "매출액",
      period: "thstrm",
      sj_div: "IS",
    },
    {
      account_id: "ifrs-full_Revenue",
      amount: "300870903000000.0000",
      name: "매출액",
      period: "frmtrm",
      sj_div: "IS",
    },
  ],
  key: "revenue_growth",
  name: "매출액증가율",
  unavailable_reason: null,
  unit: "percent",
  value: "10.88",
};

const yearPayload = {
  bsns_year: 2025,
  currency: "KRW",
  figures: [
    {
      account_id: "ifrs-full_Revenue",
      amount: "333605938000000.0000",
      key: "revenue",
      name: "매출액",
      sj_div: "IS",
    },
  ],
  fs_div: "CFS",
  indicators: [indicatorPayload],
  rcept_no: "20260310002820",
  reprt_code: "11011",
  version: 1,
};

const valuationPayload = {
  items: [
    {
      formula: "현재가 ÷ 최근 연간 기본주당이익",
      key: "per",
      name: "PER",
      unavailable_reason: null,
      unit: "ratio",
      value: "41.56",
    },
  ],
  price: { as_of: "2026-08-17T12:31:18Z", price: "274500.00000000", source: "KIS" },
  report: {
    bsns_year: 2025,
    fs_div: "CFS",
    rcept_no: "20260310002820",
    reprt_code: "11011",
    version: 1,
  },
  share_count: {
    as_of: "2026-08-17T12:31:18Z",
    share_count: 5846278608,
    source: "KIS",
    version: 1,
  },
};

const indicatorsPayload = {
  fs_div: "CFS",
  source: "DART",
  symbol: "005930",
  valuation: valuationPayload,
  years: [yearPayload],
};

describe("fundamentals schemas", () => {
  it("지표 응답 계약을 수식·출처와 함께 수용한다", () => {
    const parsed = parseFinancialIndicators(indicatorsPayload);
    const year = parsed.years[0];
    expect(year?.rcept_no).toBe("20260310002820");
    expect(year?.indicators[0]?.formula).toContain("매출액");
    expect(year?.indicators[0]?.value).toBe("10.88");
  });

  it("값이 없는 지표는 사유 코드와 함께 수용한다", () => {
    const parsed = parseFinancialIndicators({
      ...indicatorsPayload,
      years: [
        {
          ...yearPayload,
          indicators: [
            {
              ...indicatorPayload,
              inputs: [{ ...indicatorPayload.inputs[0], amount: null }],
              unavailable_reason: "MISSING_ACCOUNT",
              value: null,
            },
          ],
        },
      ],
    });
    expect(parsed.years[0]?.indicators[0]?.unavailable_reason).toBe("MISSING_ACCOUNT");
  });

  it("계약 밖 필드는 거부한다", () => {
    expect(() =>
      parseFinancialIndicators({ ...indicatorsPayload, databaseUrl: "postgresql://x" }),
    ).toThrow();
  });

  it("가치지표 블록의 기준과 항목을 수용한다", () => {
    const parsed = parseFinancialIndicators(indicatorsPayload);
    expect(parsed.valuation?.price?.price).toBe("274500.00000000");
    expect(parsed.valuation?.share_count?.share_count).toBe(5846278608);
    expect(parsed.valuation?.report.rcept_no).toBe("20260310002820");
    expect(parsed.valuation?.items[0]?.value).toBe("41.56");
  });

  it("가치지표가 없으면 null을 수용하고 기준 없는 항목은 사유와 함께 수용한다", () => {
    const noValuation = parseFinancialIndicators({ ...indicatorsPayload, valuation: null });
    expect(noValuation.valuation).toBeNull();

    const failClosed = parseFinancialIndicators({
      ...indicatorsPayload,
      valuation: {
        ...valuationPayload,
        items: [
          {
            formula: "현재가 × 보통주 상장주식수",
            key: "market_cap",
            name: "시가총액(보통주)",
            unavailable_reason: "MISSING_SHARE_COUNT",
            unit: "krw",
            value: null,
          },
        ],
        share_count: null,
      },
    });
    expect(failClosed.valuation?.items[0]?.unavailable_reason).toBe("MISSING_SHARE_COUNT");
  });

  it("보고서 목록 계약을 수용한다", () => {
    const parsed = parseFinancialReports({
      reports: [
        {
          bsns_year: 2025,
          corp_code: "00126380",
          currency: "KRW",
          fs_div: "CFS",
          rcept_no: "20260310002820",
          received_at: "2026-08-17T09:00:00Z",
          report_id: "3b9a4f6e-2f1a-4c1e-9c6c-000000000001",
          reprt_code: "11011",
          superseded_at: null,
          symbol: "005930",
          valid_from: "2026-08-17T09:00:00Z",
          version: 1,
        },
      ],
      source: "DART",
      symbol: "005930",
    });
    expect(parsed.reports[0]?.rcept_no).toBe("20260310002820");
  });
});

describe("formatKoreanAmount", () => {
  it("조 단위 금액을 한 자리 소수로 줄인다", () => {
    expect(formatKoreanAmount("333605938000000.0000")).toBe("333.6조");
    expect(formatKoreanAmount("43601051000000")).toBe("43.6조");
  });

  it("정확히 떨어지는 조 단위는 소수점을 남기지 않는다", () => {
    expect(formatKoreanAmount("45000000000000")).toBe("45조");
  });

  it("음수 금액을 지원한다", () => {
    expect(formatKoreanAmount("-15987000000000")).toBe("-16조");
  });

  it("억 단위와 그 미만을 처리한다", () => {
    expect(formatKoreanAmount("898000000000")).toBe("8,980억");
    expect(formatKoreanAmount("150")).toBe("150");
  });
});
