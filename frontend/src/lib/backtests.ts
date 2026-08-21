import { z } from "zod";

const decimal = z.string().regex(/^-?\d+(\.\d+)?([Ee][+-]?\d+)?$/);
const isoDate = z.iso.date();
const isoDateTime = z.iso.datetime();

const metricsSchema = z.strictObject({
  benchmark_return_pct: decimal,
  excess_return_pct: decimal,
  mdd_pct: decimal,
  pre_cost_return_pct: decimal,
  sharpe: decimal.nullable(),
  total_fee: decimal,
  total_return_pct: decimal,
  total_slippage: decimal,
  total_tax: decimal,
  trade_count: z.number().int(),
  turnover_pct: decimal,
});

const runSchema = z.strictObject({
  action_version_hash: z.string(),
  benchmark_dataset_id: z.uuid().nullable(),
  benchmark_symbol: z.string().min(1),
  cost_rule_versions: z.string().min(1),
  created_at: isoDateTime,
  engine_version: z.string().min(1),
  failure_code: z.string().nullable(),
  initial_cash: decimal,
  input_bar_version_hash: z.string(),
  metrics: metricsSchema.nullable(),
  parameters_json: z.string().min(1),
  range_end: isoDate,
  range_start: isoDate,
  run_id: z.uuid(),
  signal_dataset_id: z.uuid().nullable(),
  signal_method: z.string().min(1),
  status: z.enum(["completed", "failed"]),
  strategy_name: z.string().min(1),
  strategy_version: z.string().min(1),
  // 다종목 실행은 대표 종목이 없다(유니버스·매매 종목으로 식별한다).
  symbol: z.string().min(1).nullable(),
  universe_size: z.number().int().nonnegative(),
  traded_symbols: z.array(z.string()).readonly(),
});

const runsSchema = z.strictObject({
  runs: z.array(runSchema).readonly(),
});

const tradeSchema = z.strictObject({
  action: z.enum(["buy", "sell"]),
  execution_date: isoDate.nullable(),
  fee: decimal,
  gross_amount: decimal,
  price: decimal.nullable(),
  quantity: z.number().int(),
  reason: z.string().min(1),
  sequence: z.number().int(),
  signal_date: isoDate,
  skip_reason: z.string().nullable(),
  // 다종목 실행의 체결만 종목을 갖는다.
  symbol: z.string().nullable(),
  slippage: decimal,
  tax: decimal,
});

const tradesSchema = z.strictObject({
  run_id: z.uuid(),
  trades: z.array(tradeSchema).readonly(),
});

const equityPointSchema = z.strictObject({
  cash: decimal,
  nav: decimal,
  position_value: decimal,
  trading_date: isoDate,
});

const equitySchema = z.strictObject({
  equity: z.array(equityPointSchema).readonly(),
  run_id: z.uuid(),
});

export type BacktestMetrics = z.infer<typeof metricsSchema>;
export type BacktestRun = z.infer<typeof runSchema>;
export type BacktestRuns = z.infer<typeof runsSchema>;
export type BacktestTrade = z.infer<typeof tradeSchema>;
export type BacktestTrades = z.infer<typeof tradesSchema>;
export type BacktestEquityPoint = z.infer<typeof equityPointSchema>;
export type BacktestEquity = z.infer<typeof equitySchema>;

export const parseBacktestRuns = (input: unknown): BacktestRuns => runsSchema.parse(input);
export const parseBacktestTrades = (input: unknown): BacktestTrades => tradesSchema.parse(input);
export const parseBacktestEquity = (input: unknown): BacktestEquity => equitySchema.parse(input);

const parametersSchema = z.record(z.string(), z.union([z.string(), z.number()]));

export const parseStrategyParameters = (parametersJson: string): readonly [string, string][] => {
  const parsed: unknown = JSON.parse(parametersJson);
  const record = parametersSchema.parse(parsed);
  return Object.entries(record).map(([key, value]) => [key, String(value)]);
};

const costRuleVersionsSchema = z.array(z.string());

export const parseCostRuleVersions = (costRuleVersions: string): readonly string[] => {
  const parsed: unknown = JSON.parse(costRuleVersions);
  return costRuleVersionsSchema.parse(parsed);
};

// 표시 전용 파생: NAV 곡선을 초기 현금 대비 누적수익률(%)로 변환한다.
export const cumulativeReturnPct = (
  navs: readonly number[],
  initialCash: number,
): readonly number[] => navs.map((nav) => (nav / initialCash - 1) * 100);

// 표시 전용 파생: NAV 고점 대비 낙폭(%)을 계산한다. 값은 0 이하다.
export const drawdownPct = (navs: readonly number[]): readonly number[] => {
  let peak = Number.NEGATIVE_INFINITY;
  return navs.map((nav) => {
    peak = Math.max(peak, nav);
    return (nav / peak - 1) * 100;
  });
};
