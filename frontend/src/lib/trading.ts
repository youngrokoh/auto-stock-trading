import { z } from "zod";

const decimal = z.string().regex(/^-?\d+(\.\d+)?([Ee][+-]?\d+)?$/);
const isoDate = z.iso.date();
const isoDateTime = z.iso.datetime();

const automationEventSchema = z.strictObject({
  detail: z.string().nullable(),
  event_type: z.string().min(1),
  occurred_at: isoDateTime,
  previous_state: z.string().nullable(),
  reason_code: z.string().nullable(),
  state: z.string().nullable(),
});

const automationSchema = z.strictObject({
  changed_at: isoDateTime.nullable(),
  environment: z.string().min(1),
  events: z.array(automationEventSchema).readonly(),
  reason_code: z.string().nullable(),
  state: z.string().min(1),
  trading_date: isoDate.nullable(),
});

const accountPositionSchema = z.strictObject({
  average_price: decimal,
  current_price: decimal,
  evaluation_amount: decimal,
  orderable_quantity: z.number().int(),
  profit_loss: decimal,
  quantity: z.number().int(),
  symbol: z.string().min(1),
});

const accountSnapshotSchema = z.strictObject({
  account_reference: z.string().min(1),
  as_of: isoDateTime,
  broker_net_asset: decimal,
  cash_balance: decimal,
  currency: z.string().min(1),
  environment: z.string().min(1),
  nav: decimal,
  orderable_cash: decimal,
  position_value: decimal,
  positions: z.array(accountPositionSchema).readonly(),
  received_at: isoDateTime,
  snapshot_id: z.uuid(),
  source: z.string().min(1),
  trading_date: isoDate,
});

const accountSnapshotsSchema = z.strictObject({
  environment: z.string().min(1),
  snapshots: z.array(accountSnapshotSchema).readonly(),
});

const orderSchema = z.strictObject({
  average_fill_price: decimal.nullable(),
  broker_order_id: z.string().nullable(),
  client_order_id: z.string().min(1),
  created_at: isoDateTime,
  filled_quantity: z.number().int(),
  limit_price: decimal.nullable(),
  order_type: z.string().min(1),
  plan_id: z.uuid(),
  quantity: z.number().int(),
  reference_price: decimal.nullable(),
  reference_received_at: isoDateTime.nullable(),
  reference_source: z.string().nullable(),
  reject_code: z.string().nullable(),
  sequence: z.number().int(),
  side: z.enum(["buy", "sell"]),
  state: z.string().min(1),
  submitted_at: isoDateTime.nullable(),
  symbol: z.string().min(1),
  trading_date: isoDate,
});

const ordersSchema = z.strictObject({
  environment: z.string().min(1),
  orders: z.array(orderSchema).readonly(),
});

const riskLimitUsageSchema = z.strictObject({
  basis: z.string().min(1),
  comparison: z.enum(["at_most", "at_least"]),
  current_value: decimal.nullable(),
  limit_value: decimal,
  reason: z.string().nullable(),
  rule_code: z.string().min(1),
  usage_ratio: decimal.nullable(),
});

const orderConditionsSchema = z.strictObject({
  api_failure_window_seconds: z.number().int(),
  order_window_end: z.string().min(1),
  order_window_start: z.string().min(1),
  price_band: decimal,
  quote_max_age_seconds: z.number().int(),
});

const riskLimitsSchema = z.strictObject({
  basis_date: isoDate.nullable(),
  conditions: orderConditionsSchema,
  environment: z.string().min(1),
  evaluated_at: isoDateTime,
  items: z.array(riskLimitUsageSchema).readonly(),
  nav_basis: decimal.nullable(),
  peak_nav: decimal.nullable(),
  session_open_nav: decimal.nullable(),
  snapshot_as_of: isoDateTime.nullable(),
  snapshot_id: z.uuid().nullable(),
});

export type AutomationEvent = z.infer<typeof automationEventSchema>;
export type Automation = z.infer<typeof automationSchema>;
export type AccountPosition = z.infer<typeof accountPositionSchema>;
export type AccountSnapshot = z.infer<typeof accountSnapshotSchema>;
export type AccountSnapshots = z.infer<typeof accountSnapshotsSchema>;
export type TradingOrder = z.infer<typeof orderSchema>;
export type TradingOrders = z.infer<typeof ordersSchema>;
export type RiskLimitUsage = z.infer<typeof riskLimitUsageSchema>;
export type RiskLimits = z.infer<typeof riskLimitsSchema>;

export const parseAutomation = (payload: unknown): Automation => automationSchema.parse(payload);
export const parseAccountSnapshots = (payload: unknown): AccountSnapshots =>
  accountSnapshotsSchema.parse(payload);
export const parseOrders = (payload: unknown): TradingOrders => ordersSchema.parse(payload);
export const parseRiskLimits = (payload: unknown): RiskLimits => riskLimitsSchema.parse(payload);

/** 화면 디자인 사양 5.5절의 소진율 막대 색 단계. 85% 초과가 위험이다. */
export type UsageLevel = "danger" | "normal" | "unknown" | "warn";

const WARN_RATIO = 0.7;
const DANGER_RATIO = 0.85;

export const usagePercent = (ratio: string | null): number | null => {
  if (ratio === null) {
    return null;
  }
  return Number((Number.parseFloat(ratio) * 100).toFixed(1));
};

export const usageLevel = (ratio: string | null): UsageLevel => {
  if (ratio === null) {
    return "unknown";
  }
  const value = Number.parseFloat(ratio);
  if (value > DANGER_RATIO) {
    return "danger";
  }
  return value >= WARN_RATIO ? "warn" : "normal";
};

const LIMIT_LABELS: Readonly<Record<string, string>> = {
  RISK_API_FAILURES: "외부 API 연속 실패",
  RISK_CONSECUTIVE_REJECTS: "연속 주문 거절",
  RISK_DAILY_BUY_AMOUNT: "하루 신규 매수 금액",
  RISK_DAILY_LOSS: "일일 손익",
  RISK_DAILY_ORDER_ATTEMPTS: "하루 주문 시도",
  RISK_DRAWDOWN: "고점 대비 낙폭",
  RISK_MIN_CASH: "최소 현금 비중",
  RISK_OPEN_ORDERS: "동시 미체결 주문",
  RISK_ORDER_AMOUNT: "주문 1건 금액",
  RISK_SECTOR_EXPOSURE: "업종별 비중",
  RISK_SYMBOL_EXPOSURE: "종목별 비중",
  RISK_TOTAL_EXPOSURE: "총 투자 비중",
  RISK_UNCLASSIFIED_EXPOSURE: "분류되지 않은 종목 합계",
};

export const limitLabel = (ruleCode: string): string => LIMIT_LABELS[ruleCode] ?? ruleCode;

const AUTOMATION_LABELS: Readonly<Record<string, string>> = {
  armed: "준비",
  disabled: "비활성",
  emergency_stop: "비상정지",
  paused: "일시정지",
  running: "실행 중",
};

export const automationLabel = (state: string): string => AUTOMATION_LABELS[state] ?? state;

const ORDER_STATE_LABELS: Readonly<Record<string, string>> = {
  canceled: "취소",
  filled: "체결",
  partially_filled: "부분체결",
  planned: "계획",
  rejected: "거절",
  submitted: "제출",
};

export const orderStateLabel = (state: string): string => ORDER_STATE_LABELS[state] ?? state;

/** 제출 이후 상태만 증권사 체결 정보를 가진다. 계획·거절 주문에는 체결 사실이 없다. */
export const hasFillInformation = (state: string): boolean =>
  state === "submitted" || state === "partially_filled" || state === "filled";

const EVENT_LABELS: Readonly<Record<string, string>> = {
  api_failure: "API 실패",
  attestation: "사람 확인 종결",
  listener_state: "체결통보 연결",
  reconcile_problem: "대조 불일치",
  state_change: "상태 전이",
};

export const eventTypeLabel = (eventType: string): string => EVENT_LABELS[eventType] ?? eventType;

/**
 * 상태 전이와 리스너 부착은 정상 흐름이고, 나머지는 주의를 요구한다.
 * 리스너 단절은 제출이 차단된다는 뜻이므로 주의로 표시하고, 사람 확인 종결은
 * 증권사 사실이 아닌 근거로 상태가 바뀐 기록이므로 항상 주의로 표시한다.
 */
export const isAlertEvent = (eventType: string, reasonCode?: string | null): boolean => {
  if (eventType === "state_change") {
    return false;
  }
  if (eventType === "listener_state") {
    return reasonCode !== "LISTENER_ATTACHED";
  }
  return true;
};

type PositionReturnInput = Readonly<{
  average_price: string;
  profit_loss: string;
  quantity: number;
}>;

export const positionReturnPct = (position: PositionReturnInput): number | null => {
  const cost = Number.parseFloat(position.average_price) * position.quantity;
  if (cost <= 0) {
    return null;
  }
  return Number(((Number.parseFloat(position.profit_loss) / cost) * 100).toFixed(2));
};

export const positionWeightPct = (
  evaluationAmount: string,
  navBasis: string | null,
): number | null => {
  if (navBasis === null) {
    return null;
  }
  const nav = Number.parseFloat(navBasis);
  if (nav <= 0) {
    return null;
  }
  return Number(((Number.parseFloat(evaluationAmount) / nav) * 100).toFixed(2));
};
