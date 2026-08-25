import { describe, expect, it } from "vitest";

import { conditionLabel, conditionTone, parseGateReadiness } from "../src/lib/gate";

const payload = {
  blocking_codes: ["PAPER_TRADING_DAYS", "AVAILABILITY"],
  conditions: [
    {
      code: "PAPER_TRADING_DAYS",
      measured: "6",
      reason_code: null,
      requirement: "60거래일 이상 운영",
      section: "paper_operation",
      state: "not_met",
      threshold: "60",
    },
    {
      code: "AVAILABILITY",
      measured: null,
      reason_code: "NO_UPTIME_SOURCE",
      requirement: "가용성 99% 이상",
      section: "paper_operation",
      state: "not_measurable",
      threshold: null,
    },
  ],
  environment: "paper",
  evaluated_at: "2026-08-25T01:47:02Z",
  initial_limits: [{ code: "LIVE_TOTAL_EXPOSURE", item: "총 투자 비중", value: "20%" }],
  live_enabled: false,
  passed: false,
};

describe("실전 전환 게이트", () => {
  it("조건과 한도를 파싱한다", () => {
    const gate = parseGateReadiness(payload);

    expect(gate.passed).toBe(false);
    expect(gate.conditions).toHaveLength(2);
    expect(gate.initial_limits[0]?.value).toBe("20%");
  });

  it("판정 불가는 측정값이 없고 사유가 있다", () => {
    const gate = parseGateReadiness(payload);

    const availability = gate.conditions.find((item) => item.code === "AVAILABILITY");
    expect(availability?.measured).toBeNull();
    expect(availability?.reason_code).toBe("NO_UPTIME_SOURCE");
  });

  it("판정 불가는 미충족과 다른 표시를 쓴다", () => {
    expect(conditionLabel("not_measurable")).toBe("판정 불가");
    expect(conditionLabel("not_met")).toBe("미충족");
    expect(conditionTone("not_measurable")).toBe("unknown");
    expect(conditionTone("not_met")).toBe("danger");
  });

  it("모르는 상태값은 거부한다", () => {
    expect(() =>
      parseGateReadiness({
        ...payload,
        conditions: [{ ...payload.conditions[0], state: "probably_fine" }],
      }),
    ).toThrow();
  });

  it("응답에 없는 필드가 오면 거부한다", () => {
    expect(() => parseGateReadiness({ ...payload, nav: "10000000" })).toThrow();
  });
});
