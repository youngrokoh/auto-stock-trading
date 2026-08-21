import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchBacktestEquity, fetchBacktestRuns, fetchBacktestTrades } from "../api/backtests";
import { fetchAdjustedDailyBars } from "../api/market-data";
import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import type { EquityChartPoint } from "../components/equity-panes";
import { EquityPanes } from "../components/equity-panes";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import type { BacktestRun } from "../lib/backtests";
import {
  cumulativeReturnPct,
  drawdownPct,
  parseCostRuleVersions,
  parseStrategyParameters,
} from "../lib/backtests";
import {
  decimalToNumber,
  formatDecimal,
  formatKstDateTime,
  formatSignedPercent,
} from "../lib/format";

const TRADE_ROWS = 12;
// 매매 종목은 개수와 앞부분만 보여준다. 유니버스 전수는 화면에 쓸모가 없다.
const TRADED_PREVIEW = 6;

const runSubject = (run: BacktestRun): string =>
  run.symbol ?? `유니버스 ${String(run.universe_size)}종목`;

const runLabel = (run: BacktestRun): string =>
  `${run.strategy_name} v${run.strategy_version} · ${runSubject(run)} · ${run.range_start}~${run.range_end} · ${run.status === "completed" ? "완료" : "실패"}`;

const signedTone = (value: string): "down" | "neutral" | "up" => {
  const numeric = decimalToNumber(value);
  if (numeric > 0) {
    return "up";
  }
  return numeric < 0 ? "down" : "neutral";
};

const shortHash = (value: string): string => (value === "" ? "—" : `${value.slice(0, 12)}…`);

const tradeSkipLabel = (skipReason: string): string => {
  switch (skipReason) {
    case "window_end":
      return "창 종료";
    case "already_positioned":
      return "보유 중";
    case "no_position":
      return "무포지션";
    case "insufficient_cash":
      return "현금 부족";
    default:
      return skipReason;
  }
};

const isSiblingRun = (run: BacktestRun, reference: BacktestRun): boolean =>
  run.strategy_name === reference.strategy_name &&
  run.strategy_version === reference.strategy_version &&
  run.parameters_json === reference.parameters_json &&
  run.symbol === reference.symbol &&
  run.universe_size === reference.universe_size &&
  run.signal_method === reference.signal_method;

export const Strategy = () => {
  const [runId, setRunId] = useState<string | null>(null);

  const runsQuery = useQuery({
    queryFn: fetchBacktestRuns,
    queryKey: ["backtest-runs"],
    retry: false,
  });
  const runs = runsQuery.data?.runs ?? [];
  const activeRunId = runId ?? runs[0]?.run_id ?? null;
  const run = runs.find((entry) => entry.run_id === activeRunId);
  const completed = run !== undefined && run.status === "completed";

  const tradesQuery = useQuery({
    enabled: completed,
    queryFn: () => fetchBacktestTrades(activeRunId ?? ""),
    queryKey: ["backtest-trades", activeRunId],
    retry: false,
  });
  const equityQuery = useQuery({
    enabled: completed,
    queryFn: () => fetchBacktestEquity(activeRunId ?? ""),
    queryKey: ["backtest-equity", activeRunId],
    retry: false,
  });
  const benchmarkQuery = useQuery({
    enabled: completed && run.benchmark_dataset_id !== null,
    queryFn: () => fetchAdjustedDailyBars(run?.benchmark_symbol ?? "", "total_return"),
    queryKey: ["adjusted-daily-bars", run?.benchmark_symbol, "total_return"],
    retry: false,
  });

  const trades = tradesQuery.data?.trades ?? [];
  const equity = equityQuery.data?.equity ?? [];
  const metrics = run?.metrics ?? null;

  const initialCash = run === undefined ? 0 : decimalToNumber(run.initial_cash);
  const navs = equity.map((point) => decimalToNumber(point.nav));
  const strategyPcts = initialCash > 0 ? cumulativeReturnPct(navs, initialCash) : [];
  const drawdowns = drawdownPct(navs);
  const benchmarkCloseByDate = new Map(
    (benchmarkQuery.data?.bars ?? []).map((bar) => [bar.trading_date, bar.close_price]),
  );
  const benchmarkBase =
    equity.length === 0 ? null : (benchmarkCloseByDate.get(equity[0]?.trading_date ?? "") ?? null);
  const chartPoints: readonly EquityChartPoint[] = equity.map((point, index) => {
    const benchmarkClose = benchmarkCloseByDate.get(point.trading_date);
    return {
      benchmarkPct:
        benchmarkBase === null || benchmarkClose === undefined
          ? null
          : (decimalToNumber(benchmarkClose) / decimalToNumber(benchmarkBase) - 1) * 100,
      date: point.trading_date,
      drawdownPct: drawdowns[index] ?? 0,
      strategyPct: strategyPcts[index] ?? 0,
    };
  });

  const executedCount = trades.filter((trade) => trade.skip_reason === null).length;
  const recentTrades = [...trades].sort((left, right) => right.sequence - left.sequence);
  const visibleTrades = recentTrades.slice(0, TRADE_ROWS);
  // 다종목 실행은 어느 종목의 체결인지 보여야 표가 읽힌다.
  const isPortfolioRun = run !== undefined && run.symbol === null;
  const siblingRuns =
    run === undefined
      ? []
      : [...runs]
          .filter((entry) => isSiblingRun(entry, run))
          .sort((left, right) => left.range_start.localeCompare(right.range_start));
  const parameters = run === undefined ? [] : parseStrategyParameters(run.parameters_json);
  const costRuleVersions = run === undefined ? [] : parseCostRuleVersions(run.cost_rule_versions);

  return (
    <AppShell
      active="strategy"
      headerMeta={
        run === undefined ? (
          <span>백테스트 실행 전</span>
        ) : (
          <span>실행 기록 {formatKstDateTime(run.created_at)} · 저장된 결과</span>
        )
      }
      title="전략 연구"
    >
      <SafetyBanner
        description="백테스트 결과는 모의투자 검증과 전환 게이트를 통과하기 전까지 주문에 반영되지 않습니다. 모든 값은 저장된 실행 기록에서 오며 화면은 새 백테스트를 실행하지 않습니다."
        level="info"
        title="실전 반영 불가"
      />

      <div className="work__body">
        <KpiGrid columns={7} label="전략 성과 KPI">
          <CoordinateCell
            coord="A1"
            label="총수익률 (비용 후)"
            sub={run === undefined ? undefined : `초기 현금 ${formatDecimal(run.initial_cash)}원`}
            tone={metrics === null ? "neutral" : signedTone(metrics.total_return_pct)}
            value={metrics === null ? "—" : formatSignedPercent(metrics.total_return_pct)}
          />
          <CoordinateCell
            coord="A2"
            label="벤치마크"
            sub={run?.benchmark_symbol}
            value={metrics === null ? "—" : formatSignedPercent(metrics.benchmark_return_pct)}
          />
          <CoordinateCell
            coord="A3"
            label="초과수익"
            tone={metrics === null ? "neutral" : signedTone(metrics.excess_return_pct)}
            value={metrics === null ? "—" : `${formatSignedPercent(metrics.excess_return_pct)}p`}
          />
          <CoordinateCell
            coord="A4"
            label="MDD"
            tone={metrics === null ? "neutral" : "down"}
            value={metrics === null ? "—" : `${formatDecimal(metrics.mdd_pct)}%`}
          />
          <CoordinateCell
            coord="A5"
            label="샤프지수"
            value={
              metrics === null ? "—" : metrics.sharpe === null ? "—" : formatDecimal(metrics.sharpe)
            }
          />
          <CoordinateCell
            coord="A6"
            label="연 회전율"
            value={metrics === null ? "—" : `${formatDecimal(metrics.turnover_pct)}%`}
          />
          <CoordinateCell
            coord="A7"
            label="체결 횟수"
            value={metrics === null ? "—" : formatDecimal(String(metrics.trade_count))}
          />
        </KpiGrid>

        <div className="board">
          <div className="board__main">
            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">B</span> 누적 수익 곡선 · 드로다운
                </h2>
                {run !== undefined &&
                  (run.status === "completed" ? (
                    <StatusBadge kind="ok" label="미래정보 누출 검사 통과" />
                  ) : (
                    <StatusBadge kind="danger" label={run.failure_code ?? "실패"} />
                  ))}
              </div>
              <div className="card__body">
                <div className="control-row">
                  <label>
                    <span className="cell__coord">실행 </span>
                    <select
                      aria-label="실행 선택"
                      className="symbol-select run-select"
                      onChange={(event) => {
                        setRunId(event.target.value);
                      }}
                      value={activeRunId ?? ""}
                    >
                      {runs.map((entry) => (
                        <option key={entry.run_id} value={entry.run_id}>
                          {runLabel(entry)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {runsQuery.isError ? (
                  <p className="inline-error" role="alert">
                    백테스트 실행 기록을 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void runsQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : run === undefined ? (
                  <p className="card__note">
                    저장된 백테스트 실행이 없습니다. worker CLI로 백테스트를 실행하면 결과가 여기에
                    표시됩니다.
                  </p>
                ) : run.status === "failed" ? (
                  <p className="card__note">
                    이 실행은 실패로 기록됐습니다. 사유 코드: {run.failure_code ?? "unknown"}
                  </p>
                ) : (
                  <EquityPanes points={chartPoints} />
                )}
              </div>
              <div className="card__note">
                전략 곡선은 저장된 일별 NAV, 벤치마크 곡선은 발행된 total_return 수정주가
                데이터셋에서 파생한 표시 전용 값입니다
              </div>
            </section>

            <section className={trades.length === 0 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">D</span> 신호·체결 기록
                </h2>
                {trades.length > 0 && (
                  <StatusBadge
                    kind="neutral"
                    label={`전체 ${String(trades.length)}건 · 체결 ${String(executedCount)}건`}
                  />
                )}
              </div>
              <div className="card__body">
                {trades.length === 0 ? (
                  "표시할 체결 기록이 없습니다. 목표 포지션 변환은 7단계 모의 자동매매에서 구현합니다."
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">신호일</th>
                        {isPortfolioRun && <th scope="col">종목</th>}
                        <th scope="col">체결일</th>
                        <th scope="col">구분</th>
                        <th scope="col">수량</th>
                        <th scope="col">체결가</th>
                        <th scope="col">비용 합계</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleTrades.map((trade) => (
                        <tr key={trade.sequence}>
                          <td className="is-name">{trade.signal_date}</td>
                          {isPortfolioRun && <td data-label="종목">{trade.symbol ?? "—"}</td>}
                          <td data-label="체결일">
                            {trade.execution_date ??
                              `미체결 · ${tradeSkipLabel(trade.skip_reason ?? "")}`}
                          </td>
                          <td
                            className={trade.action === "buy" ? "is-up" : "is-down"}
                            data-label="구분"
                          >
                            {trade.action === "buy" ? "매수" : "매도"} · {trade.reason}
                          </td>
                          <td data-label="수량">{formatDecimal(String(trade.quantity))}</td>
                          <td data-label="체결가">
                            {trade.price === null ? "—" : formatDecimal(trade.price)}
                          </td>
                          <td data-label="비용">
                            {formatDecimal(
                              String(
                                decimalToNumber(trade.fee) +
                                  decimalToNumber(trade.slippage) +
                                  decimalToNumber(trade.tax),
                              ),
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                최근 {String(TRADE_ROWS)}건 표시 · 신호는 장 마감 데이터, 체결은 다음 거래 가능일
                시가입니다 · 목표 포지션 변환은 7단계에서 이 좌표로 확장합니다
              </div>
            </section>
          </div>

          <div className="board__aside">
            <section className={metrics === null ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">C</span> 거래비용
                </h2>
              </div>
              <div className="card__body">
                {metrics === null ? (
                  "완료된 실행을 선택하면 비용 전후 성과를 표시합니다."
                ) : (
                  <dl className="fact-list">
                    <div>
                      <dt>비용 전 수익률</dt>
                      <dd>{formatSignedPercent(metrics.pre_cost_return_pct)}</dd>
                    </div>
                    <div>
                      <dt>비용 후 수익률</dt>
                      <dd>{formatSignedPercent(metrics.total_return_pct)}</dd>
                    </div>
                    <div>
                      <dt>수수료</dt>
                      <dd>{formatDecimal(metrics.total_fee)}원</dd>
                    </div>
                    <div>
                      <dt>슬리피지</dt>
                      <dd>{formatDecimal(metrics.total_slippage)}원</dd>
                    </div>
                    <div>
                      <dt>매도세</dt>
                      <dd>{formatDecimal(metrics.total_tax)}원</dd>
                    </div>
                    <div>
                      <dt>규칙 버전</dt>
                      <dd>{costRuleVersions.join(" · ")}</dd>
                    </div>
                  </dl>
                )}
              </div>
              <div className="card__note">
                거래 안전 정책 §5 연구 기본 가정 · 매도세는 체결 연도의 법정 기준선입니다
              </div>
            </section>

            <section className={siblingRuns.length < 2 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">E</span> 워크포워드 구간
                </h2>
              </div>
              <div className="card__body">
                {siblingRuns.length < 2 ? (
                  "같은 전략·파라미터의 구간 분할 실행이 아직 없습니다. 창을 나눠 실행하면 구간별 비교를 표시합니다."
                ) : (
                  <table className="grid-table">
                    <thead>
                      <tr>
                        <th scope="col">구간</th>
                        <th scope="col">수익률</th>
                        <th scope="col">초과</th>
                        <th scope="col">MDD</th>
                      </tr>
                    </thead>
                    <tbody>
                      {siblingRuns.map((entry) => (
                        <tr key={entry.run_id}>
                          <td className="is-name">
                            {entry.range_start.slice(2)}~{entry.range_end.slice(2)}
                          </td>
                          <td
                            className={
                              entry.metrics === null
                                ? undefined
                                : decimalToNumber(entry.metrics.total_return_pct) >= 0
                                  ? "is-up"
                                  : "is-down"
                            }
                          >
                            {entry.metrics === null
                              ? (entry.failure_code ?? "실패")
                              : formatSignedPercent(entry.metrics.total_return_pct)}
                          </td>
                          <td>
                            {entry.metrics === null
                              ? "—"
                              : formatSignedPercent(entry.metrics.excess_return_pct)}
                          </td>
                          <td>
                            {entry.metrics === null
                              ? "—"
                              : `${formatDecimal(entry.metrics.mdd_pct)}%`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                워크포워드는 같은 전략·파라미터를 창 분할로 반복 실행해 비교합니다
              </div>
            </section>

            <section className={run === undefined ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">F</span> 검증·입력 계보
                </h2>
              </div>
              <div className="card__body">
                {run === undefined ? (
                  "실행을 선택하면 입력 데이터 계보와 검증 상태를 표시합니다."
                ) : (
                  <dl className="fact-list">
                    <div>
                      <dt>미래정보 누출 검사</dt>
                      <dd>
                        {run.status === "completed"
                          ? "통과 · 엔진 내장 접두 재계산 검사"
                          : `실패 · ${run.failure_code ?? "unknown"}`}
                      </dd>
                    </div>
                    <div>
                      <dt>전략</dt>
                      <dd>
                        {run.strategy_name} v{run.strategy_version}
                      </dd>
                    </div>
                    {run.symbol === null && (
                      <>
                        <div>
                          <dt>유니버스</dt>
                          <dd>{run.universe_size}종목</dd>
                        </div>
                        <div>
                          <dt>매매 종목</dt>
                          <dd>
                            {run.traded_symbols.length === 0
                              ? "체결 없음"
                              : `${String(run.traded_symbols.length)}종목 · ${run.traded_symbols
                                  .slice(0, TRADED_PREVIEW)
                                  .join(", ")}${
                                  run.traded_symbols.length > TRADED_PREVIEW ? " …" : ""
                                }`}
                          </dd>
                        </div>
                      </>
                    )}
                    <div>
                      <dt>파라미터</dt>
                      <dd>
                        {parameters
                          .map((parameter) => `${parameter[0]} ${parameter[1]}`)
                          .join(" · ")}
                      </dd>
                    </div>
                    <div>
                      <dt>신호 가격</dt>
                      <dd>{run.signal_method} 수정주가 데이터셋</dd>
                    </div>
                    <div>
                      <dt>엔진 버전</dt>
                      <dd>{run.engine_version}</dd>
                    </div>
                    <div>
                      <dt>일봉 버전 해시</dt>
                      <dd>{shortHash(run.input_bar_version_hash)}</dd>
                    </div>
                    <div>
                      <dt>기업행사 버전 해시</dt>
                      <dd>{shortHash(run.action_version_hash)}</dd>
                    </div>
                    <div>
                      <dt>신호 데이터셋</dt>
                      <dd>{run.signal_dataset_id === null ? "—" : run.signal_dataset_id}</dd>
                    </div>
                    <div>
                      <dt>벤치마크 데이터셋</dt>
                      <dd>{run.benchmark_dataset_id === null ? "—" : run.benchmark_dataset_id}</dd>
                    </div>
                  </dl>
                )}
              </div>
              <div className="card__note">
                동일 입력·파라미터·엔진 버전이면 결과가 재현됩니다 · 실패한 실행도 사유 코드와 함께
                보존됩니다
              </div>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
