import { describe, expect, it } from "vitest";

import {
  automationLabel,
  eventTypeLabel,
  hasFillInformation,
  isAlertEvent,
  limitLabel,
  orderStateLabel,
  parseAutomation,
  parseNotificationStatus,
  parseOrders,
  parseRiskLimits,
  positionReturnPct,
  positionWeightPct,
  usageLevel,
  usagePercent,
} from "../src/lib/trading";

const automationPayload = {
  changed_at: "2026-08-18T08:22:00Z",
  environment: "paper",
  events: [
    {
      detail: null,
      event_type: "state_change",
      occurred_at: "2026-08-18T08:22:00Z",
      previous_state: "running",
      reason_code: "USER_COMMAND",
      state: "disabled",
    },
    {
      detail: "account_balance:KisConfigurationError",
      event_type: "api_failure",
      occurred_at: "2026-08-18T08:10:00Z",
      previous_state: null,
      reason_code: null,
      state: null,
    },
  ],
  reason_code: "USER_COMMAND",
  stale_reason_code: null,
  state: "disabled",
  stored_state: "disabled",
  trading_date: "2026-08-18",
};

const ordersPayload = {
  environment: "paper",
  orders: [
    {
      average_fill_price: null,
      broker_order_id: null,
      client_order_id: "a".repeat(32),
      created_at: "2026-08-19T01:11:00Z",
      filled_quantity: 0,
      limit_price: "71800.00000000",
      order_type: "limit",
      plan_id: "00000000-0000-4000-8000-000000000301",
      quantity: 1,
      reference_price: "71100.00000000",
      reference_received_at: "2026-08-19T01:11:00Z",
      reference_source: "KIS",
      reject_code: null,
      sequence: 1,
      side: "buy",
      state: "planned",
      submitted_at: null,
      symbol: "005930",
      trading_date: "2026-08-19",
    },
  ],
};

const riskLimitsPayload = {
  basis_date: "2026-08-19",
  conditions: {
    api_failure_window_seconds: 300,
    order_window_end: "15:15:00",
    order_window_start: "09:05:00",
    price_band: "0.01",
    quote_max_age_seconds: 10,
  },
  environment: "paper",
  evaluated_at: "2026-08-19T01:11:30Z",
  items: [
    {
      basis: "nav_ratio",
      comparison: "at_most",
      current_value: "0.000000",
      limit_value: "0.80",
      reason: null,
      rule_code: "RISK_TOTAL_EXPOSURE",
      usage_ratio: "0.000000",
    },
    {
      basis: "nav_ratio",
      comparison: "at_most",
      current_value: null,
      limit_value: "0.30",
      reason: "MISSING_SECTOR_DATA",
      rule_code: "RISK_SECTOR_EXPOSURE",
      usage_ratio: null,
    },
  ],
  nav_basis: "10000000",
  peak_nav: "10000000",
  session_open_nav: "10000000",
  snapshot_as_of: "2026-08-19T01:10:00Z",
  snapshot_id: "00000000-0000-4000-8000-000000000302",
};

describe("trading 응답 파싱", () => {
  it("자동매매 상태와 이벤트를 파싱한다", () => {
    const parsed = parseAutomation(automationPayload);

    expect(parsed.state).toBe("disabled");
    expect(parsed.events).toHaveLength(2);
    expect(parsed.events[1]?.event_type).toBe("api_failure");
  });

  it("모르는 필드가 오면 파싱을 거부한다", () => {
    expect(() => parseAutomation({ ...automationPayload, extra: 1 })).toThrow();
  });

  it("주문 목록과 위험 한도를 파싱한다", () => {
    expect(parseOrders(ordersPayload).orders[0]?.filled_quantity).toBe(0);
    expect(parseRiskLimits(riskLimitsPayload).items[1]?.reason).toBe("MISSING_SECTOR_DATA");
  });
});

describe("소진율 표현", () => {
  it("소진율을 백분율로 바꾸고 100%를 넘겨도 값을 유지한다", () => {
    expect(usagePercent("0.137250")).toBe(13.7);
    expect(usagePercent("1.098000")).toBe(109.8);
    expect(usagePercent(null)).toBeNull();
  });

  it("사양 5.5절 색 단계를 소진율로 결정한다", () => {
    expect(usageLevel("0.690000")).toBe("normal");
    expect(usageLevel("0.700000")).toBe("warn");
    expect(usageLevel("0.850000")).toBe("warn");
    expect(usageLevel("0.850001")).toBe("danger");
    expect(usageLevel(null)).toBe("unknown");
  });

  it("정책 항목 이름을 규칙 코드로 찾는다", () => {
    expect(limitLabel("RISK_TOTAL_EXPOSURE")).toBe("총 투자 비중");
    expect(limitLabel("RISK_UNCLASSIFIED_EXPOSURE")).toBe("분류되지 않은 종목 합계");
    expect(limitLabel("RISK_UNKNOWN_RULE")).toBe("RISK_UNKNOWN_RULE");
  });
});

describe("상태 이름", () => {
  it("자동매매 상태를 한국어로 표시한다", () => {
    expect(automationLabel("running")).toBe("실행 중");
    expect(automationLabel("emergency_stop")).toBe("비상정지");
  });

  it("주문 상태를 사양 5.3절 이름으로 표시한다", () => {
    expect(orderStateLabel("planned")).toBe("계획");
    expect(orderStateLabel("partially_filled")).toBe("부분체결");
    expect(orderStateLabel("rejected")).toBe("거절");
  });

  it("세션 종료 종결을 취소와 구분해 표시한다", () => {
    // 우리가 취소한 것이 아니다(ADR-0017). 라벨이 없으면 코드가 그대로 노출된다.
    expect(orderStateLabel("expired")).toBe("기간만료");
    expect(orderStateLabel("canceled")).toBe("취소");
  });
});

describe("이벤트와 체결 정보", () => {
  it("이벤트 유형 이름을 한국어로 표시한다", () => {
    expect(eventTypeLabel("state_change")).toBe("상태 전이");
    expect(eventTypeLabel("api_failure")).toBe("API 실패");
    expect(eventTypeLabel("reconcile_problem")).toBe("대조 불일치");
    expect(eventTypeLabel("listener_state")).toBe("체결통보 연결");
    expect(eventTypeLabel("attestation")).toBe("사람 확인 종결");
    expect(eventTypeLabel("unknown_type")).toBe("unknown_type");
  });

  it("상태 전이가 아닌 이벤트는 주의로 표시한다", () => {
    expect(isAlertEvent("state_change")).toBe(false);
    expect(isAlertEvent("api_failure")).toBe(true);
    expect(isAlertEvent("reconcile_problem")).toBe(true);
  });

  it("사람 확인 종결은 증권사 사실이 아니므로 주의로 표시한다", () => {
    expect(isAlertEvent("attestation", "HUMAN_ATTESTED")).toBe(true);
  });

  it("체결통보 리스너 이벤트는 부착만 정상으로 본다", () => {
    expect(isAlertEvent("listener_state", "LISTENER_ATTACHED")).toBe(false);
    expect(isAlertEvent("listener_state", "LISTENER_DETACHED")).toBe(true);
    expect(isAlertEvent("listener_state", "LISTENER_ERROR")).toBe(true);
    expect(isAlertEvent("listener_state", null)).toBe(true);
  });

  it("제출 이후 상태만 체결 정보를 가진다", () => {
    expect(hasFillInformation("planned")).toBe(false);
    expect(hasFillInformation("rejected")).toBe(false);
    expect(hasFillInformation("submitted")).toBe(true);
    expect(hasFillInformation("partially_filled")).toBe(true);
    expect(hasFillInformation("filled")).toBe(true);
  });
});

describe("포지션 파생 값", () => {
  it("수익률은 매입금액 기준으로 계산한다", () => {
    expect(positionReturnPct({ average_price: "1000", profit_loss: "20000", quantity: 100 })).toBe(
      20,
    );
    expect(positionReturnPct({ average_price: "0", profit_loss: "0", quantity: 100 })).toBeNull();
  });

  it("비중은 NAV 기준으로 계산하고 NAV가 없으면 값을 만들지 않는다", () => {
    expect(positionWeightPct("1000000", "10000000")).toBe(10);
    expect(positionWeightPct("1000000", null)).toBeNull();
    expect(positionWeightPct("1000000", "0")).toBeNull();
  });
});

describe("거래일 변경 복귀", () => {
  it("서버가 되돌린 상태와 저장된 상태를 함께 파싱한다", () => {
    const parsed = parseAutomation({
      ...automationPayload,
      stale_reason_code: "TRADING_DAY_CHANGED",
      state: "disabled",
      stored_state: "running",
    });

    expect(parsed.state).toBe("disabled");
    expect(parsed.stored_state).toBe("running");
    expect(parsed.stale_reason_code).toBe("TRADING_DAY_CHANGED");
  });

  it("복귀가 없으면 stale 사유가 null이다", () => {
    const parsed = parseAutomation(automationPayload);

    expect(parsed.stale_reason_code).toBeNull();
    expect(parsed.state).toBe(parsed.stored_state);
  });
});

describe("외부 알림 발신 현황", () => {
  it("미발신·실패 건수를 파싱한다", () => {
    const status = parseNotificationStatus({
      environment: "paper",
      failed: 1,
      oldest_pending_at: "2026-08-24T05:03:11Z",
      pending: 3,
      recent: [
        {
          attempts: 1,
          event_occurred_at: "2026-08-24T05:03:11Z",
          kind: "order_state",
          reason: null,
          severity: "info",
          state: "sent",
        },
      ],
      sent_today: 12,
    });

    expect(status.pending).toBe(3);
    expect(status.failed).toBe(1);
    expect(status.recent[0]?.kind).toBe("order_state");
  });

  it("보낼 것이 없는 상태와 적체를 구분할 수 있다", () => {
    const quiet = parseNotificationStatus({
      environment: "paper",
      failed: 0,
      oldest_pending_at: null,
      pending: 0,
      recent: [],
      sent_today: 0,
    });

    expect(quiet.pending).toBe(0);
    expect(quiet.oldest_pending_at).toBeNull();
  });

  it("응답에 없는 필드가 오면 거부한다", () => {
    expect(() =>
      parseNotificationStatus({
        environment: "paper",
        failed: 0,
        nav: "10000000",
        oldest_pending_at: null,
        pending: 0,
        recent: [],
        sent_today: 0,
      }),
    ).toThrow();
  });
});

describe("예약 제출 차단 이벤트", () => {
  it("코드가 아니라 사람이 읽는 이름으로 보인다", () => {
    expect(eventTypeLabel("schedule_blocked")).toBe("예약 제출 차단");
  });

  it("주의가 필요한 이벤트로 분류된다", () => {
    expect(isAlertEvent("schedule_blocked", "LISTENER_NOT_ATTACHED")).toBe(true);
  });
});
