import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchEtfDetail, fetchEtfs } from "../api/etf";
import { fetchInstruments, fetchInvestorFlows } from "../api/market-data";
import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import type { EtfListing, EtfSnapshot } from "../lib/etf";
import {
  decimalToNumber,
  formatDecimal,
  formatKstDateTime,
  formatSignedDecimal,
  formatSignedPercent,
} from "../lib/format";

const METRICS = [
  { key: "change", label: "등락률" },
  { key: "volume", label: "거래량" },
  { key: "divergence", label: "괴리율" },
  { key: "tracking", label: "추적오차" },
  { key: "assets", label: "순자산" },
] as const;

type MetricKey = (typeof METRICS)[number]["key"];

const RANK_ROWS = 15;

const metricValue = (snapshot: EtfSnapshot, metric: MetricKey): number => {
  switch (metric) {
    case "change":
      return decimalToNumber(snapshot.change_percent);
    case "volume":
      return snapshot.volume;
    case "divergence":
      return Math.abs(decimalToNumber(snapshot.divergence_rate));
    case "tracking":
      return Math.abs(decimalToNumber(snapshot.tracking_error));
    case "assets":
      return snapshot.net_asset_total;
    default:
      return 0;
  }
};

const changeTone = (value: string): string | undefined => {
  const numeric = decimalToNumber(value);
  if (numeric > 0) {
    return "is-up";
  }
  return numeric < 0 ? "is-down" : undefined;
};

export const Etf = () => {
  const [metric, setMetric] = useState<MetricKey>("assets");
  const [symbol, setSymbol] = useState<string | null>(null);

  const etfsQuery = useQuery({ queryFn: fetchEtfs, queryKey: ["etfs"], retry: false });
  const etfs = etfsQuery.data?.etfs ?? [];
  const withSnapshot = etfs.filter(
    (etf): etf is EtfListing & { snapshot: EtfSnapshot } => etf.snapshot !== null,
  );
  const ranked = [...withSnapshot]
    .sort((left, right) => metricValue(right.snapshot, metric) - metricValue(left.snapshot, metric))
    .slice(0, RANK_ROWS);
  const activeSymbol = symbol ?? ranked[0]?.symbol ?? null;

  const detailQuery = useQuery({
    enabled: activeSymbol !== null,
    queryFn: () => fetchEtfDetail(activeSymbol ?? ""),
    queryKey: ["etf-detail", activeSymbol],
    retry: false,
  });
  const instrumentsQuery = useQuery({
    queryFn: fetchInstruments,
    queryKey: ["instruments"],
    retry: false,
  });
  const collectedSymbols = (instrumentsQuery.data?.instruments ?? []).map(
    (instrument) => instrument.symbol,
  );
  const flowsAvailable = activeSymbol !== null && collectedSymbols.includes(activeSymbol);
  const flowsQuery = useQuery({
    enabled: flowsAvailable,
    queryFn: () => fetchInvestorFlows(activeSymbol ?? "", 5),
    queryKey: ["investor-flows", activeSymbol],
    retry: false,
  });
  const detail = detailQuery.data;
  const flows = flowsQuery.data?.flows ?? [];

  const risers = withSnapshot.filter(
    (etf) => decimalToNumber(etf.snapshot.change_percent) > 0,
  ).length;
  const fallers = withSnapshot.filter(
    (etf) => decimalToNumber(etf.snapshot.change_percent) < 0,
  ).length;
  const maxDivergence = withSnapshot.reduce<(typeof withSnapshot)[number] | null>(
    (best, etf) =>
      best === null ||
      Math.abs(decimalToNumber(etf.snapshot.divergence_rate)) >
        Math.abs(decimalToNumber(best.snapshot.divergence_rate))
        ? etf
        : best,
    null,
  );
  const latestAsOf = withSnapshot.reduce<string | null>(
    (latest, etf) => (latest === null || etf.snapshot.as_of > latest ? etf.snapshot.as_of : latest),
    null,
  );

  return (
    <AppShell
      active="etf"
      headerMeta={
        latestAsOf === null ? (
          <span>스냅샷 수집 전</span>
        ) : (
          <span>스냅샷 기준 {formatKstDateTime(latestAsOf)} · 실시간 아님</span>
        )
      }
      title="ETF 탐색"
    >
      <SafetyBanner
        description="목록은 KIS 공식 마스터 파일, NAV·괴리율·운용사는 KIS ETF 현재가 원본 필드입니다. 스냅샷은 배치 수집 최신값이며 실시간이 아닙니다. 순자산총액 단위는 억원입니다."
        level="info"
        title="배치 수집 데이터"
      />

      <div className="work__body">
        <KpiGrid label="ETF 요약 KPI">
          <CoordinateCell
            coord="A1"
            label="ETF 종목 수"
            sub="KIS 마스터 · KOSPI"
            value={etfs.length === 0 ? "—" : formatDecimal(String(etfs.length))}
          />
          <CoordinateCell
            coord="A2"
            label="스냅샷 보유"
            value={withSnapshot.length === 0 ? "—" : formatDecimal(String(withSnapshot.length))}
          />
          <CoordinateCell
            coord="A3"
            label="상승 종목"
            tone="up"
            value={withSnapshot.length === 0 ? "—" : formatDecimal(String(risers))}
          />
          <CoordinateCell
            coord="A4"
            label="하락 종목"
            tone="down"
            value={withSnapshot.length === 0 ? "—" : formatDecimal(String(fallers))}
          />
          <CoordinateCell
            coord="A5"
            label="최대 |괴리율|"
            sub={maxDivergence?.name}
            value={
              maxDivergence === null
                ? "—"
                : `${formatDecimal(maxDivergence.snapshot.divergence_rate)}%`
            }
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
                  <span className="card__coord">B</span> 순위표
                </h2>
                <StatusBadge
                  kind="neutral"
                  label={`상위 ${String(RANK_ROWS)} · ${
                    METRICS.find((entry) => entry.key === metric)?.label ?? ""
                  }`}
                />
              </div>
              <div className="card__body">
                <div className="control-row">
                  <fieldset aria-label="정렬 기준" className="control-group">
                    {METRICS.map((entry) => (
                      <button
                        aria-pressed={entry.key === metric}
                        key={entry.key}
                        onClick={() => {
                          setMetric(entry.key);
                        }}
                        type="button"
                      >
                        {entry.label}
                      </button>
                    ))}
                  </fieldset>
                </div>
                {etfsQuery.isError ? (
                  <p className="inline-error" role="alert">
                    ETF 목록을 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void etfsQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : ranked.length === 0 ? (
                  <p className="card__note">수집된 스냅샷이 없습니다.</p>
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">종목</th>
                        <th scope="col">현재가</th>
                        <th scope="col">등락률</th>
                        <th scope="col">거래량</th>
                        <th scope="col">괴리율</th>
                        <th scope="col">순자산(억원)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ranked.map((etf) => (
                        <tr
                          className={etf.symbol === activeSymbol ? "is-attention" : undefined}
                          key={etf.symbol}
                          onClick={() => {
                            setSymbol(etf.symbol);
                          }}
                        >
                          <td className="is-name">
                            <button
                              className="link-button"
                              onClick={() => {
                                setSymbol(etf.symbol);
                              }}
                              type="button"
                            >
                              {etf.name}
                            </button>
                          </td>
                          <td className="is-key" data-label="현재가">
                            {formatDecimal(etf.snapshot.price)}
                          </td>
                          <td
                            className={changeTone(etf.snapshot.change_percent)}
                            data-label="등락률"
                          >
                            {formatSignedPercent(etf.snapshot.change_percent)}
                          </td>
                          <td data-label="거래량">{formatDecimal(String(etf.snapshot.volume))}</td>
                          <td data-label="괴리율">
                            {formatSignedPercent(etf.snapshot.divergence_rate)}
                          </td>
                          <td data-label="순자산">
                            {formatDecimal(String(etf.snapshot.net_asset_total))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                괴리율·추적오차 정렬은 절대값 기준 · 출처 KIS ETF 현재가 · 거래대금·기간 수익률
                순위는 후속 단계입니다
              </div>
            </section>
          </div>

          <div className="board__aside">
            <section className={detail === undefined ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">D</span> 선택 ETF 상세
                </h2>
              </div>
              <div className="card__body">
                {detail === undefined ? (
                  "순위표에서 ETF를 선택하면 상세를 표시합니다."
                ) : (
                  <dl className="fact-list">
                    <div>
                      <dt>종목</dt>
                      <dd>
                        {detail.name} · {detail.symbol}
                      </dd>
                    </div>
                    <div>
                      <dt>운용사</dt>
                      <dd>{detail.snapshot?.manager ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>대표지수</dt>
                      <dd>
                        {detail.snapshot === null
                          ? "—"
                          : `${detail.snapshot.index_name} × ${formatDecimal(detail.snapshot.tracking_multiple)}`}
                      </dd>
                    </div>
                    <div>
                      <dt>NAV</dt>
                      <dd>
                        {detail.snapshot === null ? "—" : `${formatDecimal(detail.snapshot.nav)}원`}
                      </dd>
                    </div>
                    <div>
                      <dt>괴리율</dt>
                      <dd>
                        {detail.snapshot === null
                          ? "—"
                          : formatSignedPercent(detail.snapshot.divergence_rate)}
                      </dd>
                    </div>
                    <div>
                      <dt>추적오차</dt>
                      <dd>
                        {detail.snapshot === null
                          ? "—"
                          : `${formatDecimal(detail.snapshot.tracking_error)}%`}
                      </dd>
                    </div>
                    <div>
                      <dt>순자산총액</dt>
                      <dd>
                        {detail.snapshot === null
                          ? "—"
                          : `${formatDecimal(String(detail.snapshot.net_asset_total))}억원`}
                      </dd>
                    </div>
                    <div>
                      <dt>상장일</dt>
                      <dd>{detail.snapshot?.listing_date ?? "—"}</dd>
                    </div>
                    <div>
                      <dt title={detail.distribution_yield.formula}>최근 12개월 분배율</dt>
                      <dd>
                        {detail.distribution_yield.value === null
                          ? "— (분배금 이력 없음)"
                          : `${formatDecimal(detail.distribution_yield.value)}% (${String(detail.distribution_yield.distribution_count)}회)`}
                      </dd>
                    </div>
                  </dl>
                )}
              </div>
              <div className="card__note">
                분배율 수식은 도움말에 표시 · 분배금 이력이 수집된 ETF만 계산합니다
              </div>
            </section>

            <section className={flows.length === 0 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">C</span> 투자자별 순매수
                </h2>
              </div>
              <div className="card__body">
                {flows.length === 0 ? (
                  "이 ETF의 투자자별 매매는 아직 수집하지 않았습니다. 수급은 수집 대상 종목만 제공됩니다."
                ) : (
                  <table className="grid-table">
                    <thead>
                      <tr>
                        <th scope="col">거래일</th>
                        <th scope="col">외국인</th>
                        <th scope="col">기관</th>
                        <th scope="col">개인</th>
                      </tr>
                    </thead>
                    <tbody>
                      {flows.map((flow) => (
                        <tr key={flow.trading_date}>
                          <td className="is-name">{flow.trading_date.slice(5)}</td>
                          <td className={flow.foreign_net_quantity > 0 ? "is-up" : "is-down"}>
                            {formatSignedDecimal(String(flow.foreign_net_quantity))}
                          </td>
                          <td className={flow.institution_net_quantity > 0 ? "is-up" : "is-down"}>
                            {formatSignedDecimal(String(flow.institution_net_quantity))}
                          </td>
                          <td className={flow.individual_net_quantity > 0 ? "is-up" : "is-down"}>
                            {formatSignedDecimal(String(flow.individual_net_quantity))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">순매수 수량(주) · 출처 KIS 일별 확정치(당일 제외)</div>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
