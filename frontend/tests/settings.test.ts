import { describe, expect, it } from "vitest";

import { isResearchAssumption, parseCostRules, ratePercent } from "../src/lib/settings";

const payload = {
  evaluated_on: "2026-08-25",
  rules: [
    {
      current: true,
      effective_from: "2026-01-01",
      etf_slippage_rate: "0.0005",
      fee_rate: "0.0002",
      kosdaq_stock_sell_tax_rate: "0.0020",
      kospi_stock_sell_tax_rate: "0.0020",
      source: "거래 안전 정책 §5 (증권거래세법 시행령)",
      stock_slippage_rate: "0.0010",
      version: "research-krx-2026",
    },
    {
      current: false,
      effective_from: "2024-01-01",
      etf_slippage_rate: "0.0005",
      fee_rate: "0.0002",
      kosdaq_stock_sell_tax_rate: "0.0018",
      kospi_stock_sell_tax_rate: "0.0018",
      source: "연구 가정: 증권거래세 단계 인하 일정",
      stock_slippage_rate: "0.0010",
      version: "research-krx-2024",
    },
  ],
};

describe("거래비용 규칙", () => {
  it("규칙 세트를 파싱한다", () => {
    const rules = parseCostRules(payload);

    expect(rules.rules).toHaveLength(2);
    expect(rules.rules[0]?.current).toBe(true);
  });

  it("비율을 정책 문서와 같은 퍼센트 단위로 보여준다", () => {
    expect(ratePercent("0.0002")).toBe("0.02%");
    expect(ratePercent("0.0020")).toBe("0.2%");
    expect(ratePercent("0.0015")).toBe("0.15%");
  });

  it("읽을 수 없는 비율은 값을 만들지 않는다", () => {
    expect(ratePercent("")).toBe("—");
  });

  it("연구 가정과 공식 고시를 구분한다", () => {
    expect(isResearchAssumption("연구 가정: 증권거래세 단계 인하 일정")).toBe(true);
    expect(isResearchAssumption("거래 안전 정책 §5 (증권거래세법 시행령)")).toBe(false);
  });

  it("응답에 없는 필드가 오면 거부한다", () => {
    expect(() => parseCostRules({ ...payload, nav: "10000000" })).toThrow();
  });
});
