import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  fetchCorporateActions,
  fetchDailyBars,
  fetchInstruments,
  fetchQuote,
} from "../api/market-data";
import { AppShell } from "../components/app-shell";
import type { ChartBar } from "../components/chart-panes";
import { ChartPanes } from "../components/chart-panes";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import {
  decimalToNumber,
  formatDecimal,
  formatKstDateTime,
  formatSignedDecimal,
  formatSignedPercent,
  marketDirection,
} from "../lib/format";
import type { DailyBar } from "../lib/market-data";

const RANGES = [
  { days: 31, key: "1M", label: "1개월" },
  { days: 92, key: "3M", label: "3개월" },
  { days: 183, key: "6M", label: "6개월" },
  { days: null, key: "ALL", label: "전체" },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

const OHLCV_ROWS = 12;

const actionTypeLabel: Readonly<Record<string, string>> = {
  cash_dividend: "현금배당",
  etf_distribution: "ETF 분배금",
};

const startDateFor = (days: number | null): string | undefined => {
  if (days === null) {
    return undefined;
  }
  const start = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  return start.toISOString().slice(0, 10);
};

const toChartBar = (bar: DailyBar): ChartBar => ({
  close: decimalToNumber(bar.close_price),
  confirmed: bar.finality === "confirmed",
  date: bar.trading_date,
  high: decimalToNumber(bar.high_price),
  low: decimalToNumber(bar.low_price),
  open: decimalToNumber(bar.open_price),
  volume: bar.volume,
});

export const Market = () => {
  const [symbol, setSymbol] = useState<string | null>(null);
  const [range, setRange] = useState<RangeKey>("3M");

  const instrumentsQuery = useQuery({
    queryFn: fetchInstruments,
    queryKey: ["instruments"],
    retry: false,
  });
  const instruments = instrumentsQuery.data?.instruments ?? [];
  const activeSymbol = symbol ?? instruments[0]?.symbol ?? null;
  const activeInstrument = instruments.find((entry) => entry.symbol === activeSymbol);
  const rangeDays = RANGES.find((entry) => entry.key === range)?.days ?? null;

  const quoteQuery = useQuery({
    enabled: activeSymbol !== null,
    queryFn: () => fetchQuote(activeSymbol ?? ""),
    queryKey: ["quote", activeSymbol],
    retry: false,
  });
  const barsQuery = useQuery({
    enabled: activeSymbol !== null,
    queryFn: () => fetchDailyBars(activeSymbol ?? "", startDateFor(rangeDays)),
    queryKey: ["daily-bars", activeSymbol, range],
    retry: false,
  });
  const actionsQuery = useQuery({
    enabled: activeSymbol !== null,
    queryFn: () => fetchCorporateActions(activeSymbol ?? ""),
    queryKey: ["corporate-actions", activeSymbol],
    retry: false,
  });

  const quote = quoteQuery.data;
  const bars = barsQuery.data?.bars ?? [];
  const chartBars = bars.map(toChartBar);
  const recentBars = bars.slice(-OHLCV_ROWS).reverse();
  const pendingCount = bars.filter((bar) => bar.finality === "pending").length;
  const actions = [...(actionsQuery.data?.actions ?? [])].sort((left, right) =>
    (right.ex_date ?? right.announcement_date).localeCompare(
      left.ex_date ?? left.announcement_date,
    ),
  );
  const direction = quote === undefined ? "flat" : marketDirection(quote.change);
  const quoteTone = direction === "up" ? "up" : direction === "down" ? "down" : "neutral";
  const quoteAsOf = quote === undefined ? undefined : formatKstDateTime(quote.received_at);

  return (
    <AppShell
      active="market"
      headerMeta={
        quoteAsOf === undefined ? (
          <span>시세 확인 전</span>
        ) : (
          <span>시세 기준 {quoteAsOf} · 실시간 아님</span>
        )
      }
      title="시장 데이터"
    >
      <SafetyBanner
        description="이 화면의 시세와 일봉은 KIS 모의환경에서 배치 수집한 값이며 실시간이 아닙니다. 미확정(pending) 일봉은 보조지표 계산에서 제외됩니다."
        level="info"
        title="배치 수집 데이터"
      />

      <div className="work__body">
        <div className="control-row">
          <label>
            <span className="cell__coord">종목 </span>
            <select
              aria-label="종목 선택"
              className="symbol-select"
              onChange={(event) => {
                setSymbol(event.target.value);
              }}
              value={activeSymbol ?? ""}
            >
              {instruments.map((instrument) => (
                <option key={instrument.symbol} value={instrument.symbol}>
                  {instrument.name} {instrument.symbol}
                </option>
              ))}
            </select>
          </label>
          <fieldset aria-label="조회 기간" className="control-group">
            {RANGES.map((entry) => (
              <button
                aria-pressed={entry.key === range}
                key={entry.key}
                onClick={() => {
                  setRange(entry.key);
                }}
                type="button"
              >
                {entry.label}
              </button>
            ))}
          </fieldset>
        </div>

        <KpiGrid label="시세 KPI">
          <CoordinateCell
            coord="A1"
            label="현재가 (원)"
            sub={quoteAsOf === undefined ? "조회 전" : `${quoteAsOf} 기준`}
            tone="stale"
            value={quote === undefined ? "—" : formatDecimal(quote.price)}
          />
          <CoordinateCell
            coord="A2"
            label="전일 대비"
            tone={quoteTone}
            value={quote === undefined ? "—" : formatSignedDecimal(quote.change)}
          />
          <CoordinateCell
            coord="A3"
            label="등락률"
            tone={quoteTone}
            value={quote === undefined ? "—" : formatSignedPercent(quote.change_percent)}
          />
          <CoordinateCell
            coord="A4"
            label="거래량 (주)"
            value={quote === undefined ? "—" : formatDecimal(String(quote.volume))}
          />
          <CoordinateCell
            coord="A5"
            label="거래대금 (원)"
            value={quote === undefined ? "—" : formatDecimal(quote.trading_value)}
          />
          <CoordinateCell
            coord="A6"
            label="데이터 상태"
            sub="실시간 아님 · 수집 시점 값"
            tone="warn"
            value="지연 데이터"
          />
        </KpiGrid>

        <div className="board">
          <div className="board__main">
            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">B</span> 일봉 차트
                </h2>
                <StatusBadge
                  kind={pendingCount > 0 ? "warn" : "ok"}
                  label={pendingCount > 0 ? `미확정 ${String(pendingCount)}봉 제외` : "전체 확정"}
                />
              </div>
              <div className="card__body">
                {barsQuery.isError ? (
                  <p className="inline-error" role="alert">
                    일봉을 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void barsQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : (
                  <ChartPanes bars={chartBars} />
                )}
              </div>
              <div className="card__note">
                단위 원·주 · 출처 KIS 비수정 일봉 · 이동평균과 밴드는 확정 봉만 사용합니다
              </div>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">C</span> OHLCV
                </h2>
              </div>
              <div className="card__body">
                <table className="grid-table grid-table--stack">
                  <thead>
                    <tr>
                      <th scope="col">거래일</th>
                      <th scope="col">시가</th>
                      <th scope="col">고가</th>
                      <th scope="col">저가</th>
                      <th scope="col">종가</th>
                      <th scope="col">거래량</th>
                      <th scope="col">상태</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentBars.map((bar) => (
                      <tr
                        className={bar.finality === "pending" ? "is-attention" : undefined}
                        key={bar.trading_date}
                      >
                        <td data-label="거래일">{bar.trading_date}</td>
                        <td data-label="시가">{formatDecimal(bar.open_price)}</td>
                        <td data-label="고가">{formatDecimal(bar.high_price)}</td>
                        <td data-label="저가">{formatDecimal(bar.low_price)}</td>
                        <td className="is-key" data-label="종가">
                          {formatDecimal(bar.close_price)}
                        </td>
                        <td data-label="거래량">{formatDecimal(String(bar.volume))}</td>
                        <td data-label="상태">
                          <StatusBadge
                            kind={bar.finality === "confirmed" ? "ok" : "warn"}
                            label={bar.finality === "confirmed" ? "확정" : "대기"}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {recentBars.length === 0 && !barsQuery.isPending && (
                  <p className="card__note">조회 구간에 일봉이 없습니다.</p>
                )}
              </div>
              <div className="card__note">
                최근 {String(OHLCV_ROWS)}거래일 · 단위 원·주 · 출처 KIS 비수정 일봉
              </div>
            </section>
          </div>

          <div className="board__aside">
            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D1</span> 종목 정보
                </h2>
              </div>
              <div className="card__body">
                {activeInstrument === undefined ? (
                  <p className="card__note">종목 정보를 불러오는 중입니다.</p>
                ) : (
                  <dl className="fact-list">
                    <div>
                      <dt>종목코드</dt>
                      <dd>{activeInstrument.symbol}</dd>
                    </div>
                    <div>
                      <dt>시장</dt>
                      <dd>
                        {activeInstrument.exchange} · {activeInstrument.country}
                      </dd>
                    </div>
                    <div>
                      <dt>상품 유형</dt>
                      <dd>{activeInstrument.product_type === "etf" ? "ETF" : "주식"}</dd>
                    </div>
                    <div>
                      <dt>통화</dt>
                      <dd>{activeInstrument.currency}</dd>
                    </div>
                    <div>
                      <dt>상장일</dt>
                      <dd>{activeInstrument.listed_on ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>기준일</dt>
                      <dd>{activeInstrument.source_as_of}</dd>
                    </div>
                  </dl>
                )}
              </div>
              <div className="card__note">출처 {activeInstrument?.source ?? "KIS"} 종목 응답</div>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D2</span> 기업행사
                </h2>
              </div>
              <div className="card__body">
                {actions.length === 0 ? (
                  <p className="card__note">
                    {actionsQuery.isError
                      ? "기업행사를 불러오지 못했습니다."
                      : "수집된 기업행사가 없습니다."}
                  </p>
                ) : (
                  <table className="grid-table">
                    <thead>
                      <tr>
                        <th scope="col">유형</th>
                        <th scope="col">락일</th>
                        <th scope="col">주당 (원)</th>
                        <th scope="col">상태</th>
                      </tr>
                    </thead>
                    <tbody>
                      {actions.slice(0, 8).map((action) => (
                        <tr key={action.action_key}>
                          <td className="is-name">
                            {actionTypeLabel[action.action_type] ?? action.action_type}
                          </td>
                          <td>{action.ex_date ?? "—"}</td>
                          <td className="is-key">
                            {action.cash_amount === null ? "—" : formatDecimal(action.cash_amount)}
                          </td>
                          <td>
                            <StatusBadge
                              kind={action.quality === "verified" ? "ok" : "warn"}
                              label={action.quality === "verified" ? "검증" : "대기"}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">출처 DART·KODEX 공식 자료 · 락일은 검증된 달력 기준</div>
            </section>

            <section className="card card--empty">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D3</span> 수급 · 신호
                </h2>
              </div>
              <div className="card__body">
                투자자별 수급은 기업 분석 화면에서 제공합니다. 전략 신호는 아직 만들지 않았으며
                6단계에서 제공됩니다.
              </div>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
