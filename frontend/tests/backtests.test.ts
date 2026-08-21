import { describe, expect, it } from "vitest";

import {
  cumulativeReturnPct,
  drawdownPct,
  parseBacktestEquity,
  parseBacktestRuns,
  parseBacktestTrades,
  parseCostRuleVersions,
  parseStrategyParameters,
} from "../src/lib/backtests";

const runPayload = {
  action_version_hash: "d".repeat(64),
  benchmark_dataset_id: "00000000-0000-4000-8000-000000000202",
  benchmark_symbol: "069500",
  cost_rule_versions: '["research-krx-2025","research-krx-2026"]',
  created_at: "2026-08-18T02:00:00Z",
  engine_version: "backtest-1",
  failure_code: null,
  initial_cash: "10000000",
  input_bar_version_hash: "c".repeat(64),
  metrics: {
    benchmark_return_pct: "254.49",
    excess_return_pct: "-210.14",
    mdd_pct: "-14.73",
    pre_cost_return_pct: "50.12",
    sharpe: "1.1502",
    total_fee: "57634",
    total_return_pct: "44.35",
    total_slippage: "288217",
    total_tax: "231440",
    trade_count: 23,
    turnover_pct: "1435.38",
  },
  parameters_json: '{"long_period":20,"rsi_overbought":"70","rsi_period":14,"short_period":5}',
  range_end: "2026-08-14",
  range_start: "2025-01-02",
  run_id: "00000000-0000-4000-8000-000000000101",
  signal_dataset_id: "00000000-0000-4000-8000-000000000201",
  signal_method: "total_return",
  status: "completed",
  strategy_name: "ma-rsi",
  strategy_version: "1",
  symbol: "005930",
  traded_symbols: [],
  universe_size: 0,
};

describe("backtest schemas", () => {
  it("실행 목록 계약을 실패 실행과 함께 수용한다", () => {
    const parsed = parseBacktestRuns({
      runs: [
        runPayload,
        {
          ...runPayload,
          benchmark_dataset_id: null,
          failure_code: "missing_adjusted_dataset",
          metrics: null,
          run_id: "00000000-0000-4000-8000-000000000102",
          signal_dataset_id: null,
          status: "failed",
        },
      ],
    });
    expect(parsed.runs).toHaveLength(2);
    expect(parsed.runs[0]?.metrics?.total_return_pct).toBe("44.35");
    expect(parsed.runs[1]?.failure_code).toBe("missing_adjusted_dataset");
  });

  it("알 수 없는 필드는 strict 계약 위반으로 거부한다", () => {
    expect(() => parseBacktestRuns({ runs: [{ ...runPayload, extra: 1 }] })).toThrow();
  });

  it("체결 계약이 미체결 사유와 널 체결가를 수용한다", () => {
    const parsed = parseBacktestTrades({
      run_id: runPayload.run_id,
      trades: [
        {
          action: "sell",
          execution_date: null,
          fee: "0",
          gross_amount: "0",
          price: null,
          quantity: 0,
          reason: "dead_cross",
          sequence: 2,
          signal_date: "2026-08-13",
          skip_reason: "window_end",
          symbol: null,
          slippage: "0",
          tax: "0",
        },
      ],
    });
    expect(parsed.trades[0]?.skip_reason).toBe("window_end");
  });

  it("NAV 곡선 계약을 수용한다", () => {
    const parsed = parseBacktestEquity({
      equity: [
        { cash: "403", nav: "1014403", position_value: "1014000", trading_date: "2026-08-10" },
      ],
      run_id: runPayload.run_id,
    });
    expect(parsed.equity[0]?.nav).toBe("1014403");
  });

  it("파라미터와 비용 규칙 버전 JSON을 표시용으로 해석한다", () => {
    expect(parseStrategyParameters(runPayload.parameters_json)).toEqual([
      ["long_period", "20"],
      ["rsi_overbought", "70"],
      ["rsi_period", "14"],
      ["short_period", "5"],
    ]);
    expect(parseCostRuleVersions(runPayload.cost_rule_versions)).toEqual([
      "research-krx-2025",
      "research-krx-2026",
    ]);
  });
});

describe("display derivations", () => {
  it("누적수익률은 초기 현금 대비 퍼센트다", () => {
    const pct = cumulativeReturnPct([1_000_000, 1_014_403, 948_959], 1_000_000);
    expect(pct[0]).toBe(0);
    expect(pct[1]).toBeCloseTo(1.4403, 10);
    expect(pct[2]).toBeCloseTo(-5.1041, 10);
  });

  it("드로다운은 고점 대비 낙폭이며 0 이하다", () => {
    const drawdown = drawdownPct([100, 110, 99, 104.5]);
    expect(drawdown[0]).toBe(0);
    expect(drawdown[1]).toBe(0);
    expect(drawdown[2]).toBeCloseTo(-10, 10);
    expect(drawdown[3]).toBeCloseTo(-5, 10);
  });

  it("다종목 실행은 대표 종목 없이 유니버스로 식별된다", () => {
    // 실측 결함: 읽기 API가 대표 종목 없는 실행을 목록에서 빼버려 화면에 보이지 않았다.
    const portfolio = {
      ...runPayload,
      strategy_name: "cross-momentum",
      symbol: null,
      traded_symbols: ["000660", "278470"],
      universe_size: 200,
    };

    const parsed = parseBacktestRuns({ runs: [portfolio] });

    expect(parsed.runs[0]?.symbol).toBeNull();
    expect(parsed.runs[0]?.universe_size).toBe(200);
    expect(parsed.runs[0]?.traded_symbols).toEqual(["000660", "278470"]);
  });
});
