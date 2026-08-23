import { describe, expect, it } from "vitest";

import { formatDecimal, formatKoreanAmount } from "../src/lib/format";
import {
  parseDisclosures,
  parseFinancialIndicators,
  parseFinancialReports,
} from "../src/lib/fundamentals";

const indicatorPayload = {
  category: "growth",
  formula: "(당기 매출액 - 전기 매출액) ÷ |전기 매출액| × 100",
  inputs: [
    {
      account_id: "ifrs-full_Revenue",
      amount: "333605938000000.0000",
      name: "매출액",
      period: "thstrm",
      resolution: "standard_account",
      sj_div: "IS",
    },
    {
      account_id: "ifrs-full_Revenue",
      amount: "300870903000000.0000",
      name: "매출액",
      period: "frmtrm",
      resolution: "standard_account",
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
      resolution: "standard_account",
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
  share_classes: [
    {
      as_of: "2026-08-23T04:39:00Z",
      class_kind: "common",
      market_cap: "1645727428152000.00000000",
      name: "삼성전자",
      price: "281500.00000000",
      share_count: 5846278608,
      share_count_as_of: "2026-08-23T04:39:00Z",
      symbol: "005930",
      volume: 27746471,
    },
    {
      as_of: "2026-08-23T04:39:00Z",
      class_kind: "preferred",
      market_cap: "166090839021000.00000000",
      name: "삼성전자우",
      price: "207000.00000000",
      share_count: 802371203,
      share_count_as_of: "2026-08-23T04:39:00Z",
      symbol: "005935",
      volume: 10625176,
    },
  ],
  items: [
    {
      formula: "보통주 현재가 ÷ 최근 연간 기본주당이익",
      key: "per",
      name: "PER",
      resolution: "standard_account",
      unavailable_reason: null,
      unit: "ratio",
      value: "41.56",
    },
    {
      formula: "최근 연간 지배주주지분 ÷ 보통주 상장주식수",
      key: "bps",
      name: "주당순자산(보통주)",
      resolution: "standard_account",
      unavailable_reason: "PREFERRED_ALLOCATION_REQUIRED",
      unit: "krw",
      value: null,
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
            formula: "보통주 현재가 × 보통주 상장주식수",
            resolution: "standard_account",
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

describe("formatDecimal", () => {
  it("지수 표기를 일반 표기로 정규화한다", () => {
    expect(formatDecimal("0E-8")).toBe("0");
    expect(formatDecimal("-0E-8")).toBe("0");
    expect(formatDecimal("1.5E+2")).toBe("150");
  });
});

describe("disclosures schema", () => {
  it("공시 목록 계약을 유형·접수번호와 함께 수용한다", () => {
    const parsed = parseDisclosures({
      disclosures: [
        {
          disclosure_type: "A",
          flr_nm: "삼성전자",
          rcept_dt: "2026-08-14",
          rcept_no: "20260814003699",
          received_at: "2026-08-17T13:16:20Z",
          report_nm: "반기보고서 (2026.06)",
        },
      ],
      source: "DART",
      symbol: "005930",
    });
    expect(parsed.disclosures[0]?.rcept_no).toBe("20260814003699");
    expect(parsed.disclosures[0]?.disclosure_type).toBe("A");
  });

  it("계약 밖 필드는 거부한다", () => {
    expect(() =>
      parseDisclosures({ symbol: "005930", source: "DART", disclosures: [], x: 1 }),
    ).toThrow();
  });
});

describe("복원한 입력", () => {
  it("복원 방식이 응답에서 구별된다", () => {
    const restored = {
      ...indicatorPayload,
      inputs: [
        { ...indicatorPayload.inputs[0], resolution: "identity_verified" },
        { ...indicatorPayload.inputs[1], resolution: "standard_difference" },
      ],
    };

    const parsed = parseFinancialIndicators({
      ...indicatorsPayload,
      years: [{ ...yearPayload, indicators: [restored] }],
    });

    expect(parsed.years[0]?.indicators[0]?.inputs[0]?.resolution).toBe("identity_verified");
    expect(parsed.years[0]?.indicators[0]?.inputs[1]?.resolution).toBe("standard_difference");
  });

  it("모르는 복원 방식은 파싱을 거부한다", () => {
    const bad = {
      ...indicatorPayload,
      inputs: [{ ...indicatorPayload.inputs[0], resolution: "guessed_by_name" }],
    };

    expect(() =>
      parseFinancialIndicators({
        ...indicatorsPayload,
        years: [{ ...yearPayload, indicators: [bad] }],
      }),
    ).toThrow();
  });
});

describe("상장 클래스", () => {
  it("클래스 내역과 우선주 사유를 파싱한다", () => {
    const parsed = parseFinancialIndicators(indicatorsPayload);

    const classes = parsed.valuation?.share_classes ?? [];
    expect(classes.map((entry) => entry.class_kind)).toEqual(["common", "preferred"]);
    expect(classes[1]?.symbol).toBe("005935");
    const bps = parsed.valuation?.items.find((item) => item.key === "bps");
    expect(bps?.unavailable_reason).toBe("PREFERRED_ALLOCATION_REQUIRED");
  });

  it("거래가 없는 우선주의 0 거래량과 기준시각을 수용한다", () => {
    const stale = {
      ...indicatorsPayload,
      valuation: {
        ...valuationPayload,
        share_classes: [
          valuationPayload.share_classes[0],
          {
            ...valuationPayload.share_classes[1],
            as_of: "2026-08-22T06:30:00Z",
            symbol: "00088K",
            volume: 0,
          },
        ],
      },
    };

    const parsed = parseFinancialIndicators(stale);

    const preferred = parsed.valuation?.share_classes[1];
    expect(preferred?.volume).toBe(0);
    expect(preferred?.as_of).toBe("2026-08-22T06:30:00Z");
  });

  it("모르는 클래스 구분은 파싱을 거부한다", () => {
    const bad = {
      ...indicatorsPayload,
      valuation: {
        ...valuationPayload,
        share_classes: [{ ...valuationPayload.share_classes[0], class_kind: "bond" }],
      },
    };

    expect(() => parseFinancialIndicators(bad)).toThrow();
  });
});
