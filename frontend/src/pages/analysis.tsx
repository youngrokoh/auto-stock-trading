import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  fetchFinancialIndicators,
  fetchFinancialReportDetail,
  fetchFinancialReports,
} from "../api/fundamentals";
import { fetchInstruments } from "../api/market-data";
import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import type { FigureYear } from "../components/figure-bars";
import { FigureBars } from "../components/figure-bars";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import { decimalToNumber, formatDecimal, formatKoreanAmount } from "../lib/format";
import type { AnnualIndicators, FinancialIndicator } from "../lib/fundamentals";

type FsDiv = "CFS" | "OFS";

const FS_DIVS = [
  { key: "CFS", label: "연결" },
  { key: "OFS", label: "개별" },
] as const;

const STATEMENT_TABS = [
  { key: "BS", label: "재무상태표" },
  { key: "IS", label: "손익계산서" },
  { key: "CIS", label: "포괄손익" },
  { key: "CF", label: "현금흐름표" },
  { key: "SCE", label: "자본변동표" },
] as const;

type StatementKey = (typeof STATEMENT_TABS)[number]["key"];

const CATEGORY_LABEL: Readonly<Record<FinancialIndicator["category"], string>> = {
  growth: "성장성",
  profitability: "수익성",
  stability: "안정성",
};

const UNAVAILABLE_LABEL: Readonly<Record<string, string>> = {
  AMBIGUOUS_ACCOUNT: "계정 중복",
  MISSING_ACCOUNT: "계정 없음",
  MISSING_AMOUNT: "금액 없음",
  ZERO_DENOMINATOR: "분모 0",
};

const figureAmount = (year: AnnualIndicators | undefined, key: string): string | null =>
  year?.figures.find((figure) => figure.key === key)?.amount ?? null;

const indicatorOf = (
  year: AnnualIndicators | undefined,
  key: string,
): FinancialIndicator | undefined => year?.indicators.find((entry) => entry.key === key);

const percentText = (indicator: FinancialIndicator | undefined): string =>
  indicator?.value == null ? "—" : `${formatDecimal(indicator.value)}%`;

const signTone = (indicator: FinancialIndicator | undefined): "up" | "down" | "neutral" => {
  if (indicator?.value == null) {
    return "neutral";
  }
  const numeric = decimalToNumber(indicator.value);
  if (numeric > 0) {
    return "up";
  }
  return numeric < 0 ? "down" : "neutral";
};

const koreanAmountOrEmpty = (amount: string | null): string =>
  amount === null ? "—" : formatKoreanAmount(amount);

const toFigureYear = (year: AnnualIndicators): FigureYear => {
  const amount = (key: string): number | null => {
    const raw = figureAmount(year, key);
    return raw === null ? null : decimalToNumber(raw);
  };
  return {
    netIncome: amount("net_income"),
    operatingIncome: amount("operating_income"),
    revenue: amount("revenue"),
    year: year.bsns_year,
  };
};

type StatementLinesProps = Readonly<{
  reportId: string | undefined;
  statement: StatementKey;
}>;

const StatementLines = ({ reportId, statement }: StatementLinesProps) => {
  const detailQuery = useQuery({
    enabled: reportId !== undefined,
    queryFn: () => fetchFinancialReportDetail(reportId ?? ""),
    queryKey: ["financial-report-detail", reportId],
    retry: false,
  });
  if (reportId === undefined) {
    return <p className="card__note">표시할 보고서가 없습니다.</p>;
  }
  if (detailQuery.isError) {
    return (
      <p className="inline-error" role="alert">
        재무제표 라인을 불러오지 못했습니다.
        <button
          className="retry-button"
          onClick={() => {
            void detailQuery.refetch();
          }}
          type="button"
        >
          다시 시도
        </button>
      </p>
    );
  }
  const lines = (detailQuery.data?.lines ?? []).filter((line) => line.sj_div === statement);
  if (lines.length === 0) {
    return (
      <p className="card__note">
        {detailQuery.isPending
          ? "재무제표 라인을 불러오는 중입니다."
          : "해당 구분의 라인이 없습니다."}
      </p>
    );
  }
  return (
    <div className="table-scroll">
      <table className="grid-table">
        <thead>
          <tr>
            <th scope="col">계정</th>
            <th scope="col">당기</th>
            <th scope="col">전기</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.line_seq}>
              <td className="is-name" title={line.account_id ?? undefined}>
                {line.account_nm}
                {line.account_detail !== null && line.sj_div === "SCE"
                  ? ` (${line.account_detail})`
                  : ""}
              </td>
              <td className="is-key">
                {line.thstrm_amount === null ? "—" : formatDecimal(line.thstrm_amount)}
              </td>
              <td>{line.frmtrm_amount === null ? "—" : formatDecimal(line.frmtrm_amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export const Analysis = () => {
  const [symbol, setSymbol] = useState<string | null>(null);
  const [fsDiv, setFsDiv] = useState<FsDiv>("CFS");
  const [statement, setStatement] = useState<StatementKey>("BS");
  const [reportId, setReportId] = useState<string | null>(null);

  const instrumentsQuery = useQuery({
    queryFn: fetchInstruments,
    queryKey: ["instruments"],
    retry: false,
  });
  const stocks = (instrumentsQuery.data?.instruments ?? []).filter(
    (instrument) => instrument.product_type === "stock",
  );
  const activeSymbol = symbol ?? stocks[0]?.symbol ?? null;

  const indicatorsQuery = useQuery({
    enabled: activeSymbol !== null,
    queryFn: () => fetchFinancialIndicators(activeSymbol ?? "", fsDiv),
    queryKey: ["financial-indicators", activeSymbol, fsDiv],
    retry: false,
  });
  const reportsQuery = useQuery({
    enabled: activeSymbol !== null,
    queryFn: () => fetchFinancialReports(activeSymbol ?? ""),
    queryKey: ["financial-reports", activeSymbol],
    retry: false,
  });

  const years = indicatorsQuery.data?.years ?? [];
  const latest = years.at(-1);
  const fsDivLabel = fsDiv === "CFS" ? "연결" : "개별";
  const basisSub =
    latest === undefined
      ? "연간 보고서 없음"
      : `${String(latest.bsns_year)} 사업보고서 · ${fsDivLabel}`;

  const annualReports = (reportsQuery.data?.reports ?? [])
    .filter((report) => report.reprt_code === "11011" && report.fs_div === fsDiv)
    .sort((left, right) => left.bsns_year - right.bsns_year);
  const selectedReport =
    annualReports.find((report) => report.report_id === reportId) ?? annualReports.at(-1);

  const revenueGrowth = indicatorOf(latest, "revenue_growth");
  const operatingMargin = indicatorOf(latest, "operating_margin");
  const roe = indicatorOf(latest, "roe");
  const debtRatio = indicatorOf(latest, "debt_ratio");

  const categories = (["growth", "profitability", "stability"] as const).map((category) => ({
    category,
    keys: (latest?.indicators ?? [])
      .filter((indicator) => indicator.category === category)
      .map((indicator) => indicator.key),
  }));

  return (
    <AppShell
      active="analysis"
      headerMeta={
        latest === undefined ? (
          <span>연간 보고서 확인 전</span>
        ) : (
          <span>
            {String(latest.bsns_year)} 사업보고서 · 접수번호 {latest.rcept_no}
          </span>
        )
      }
      title="기업 분석"
    >
      <SafetyBanner
        description={`지표는 DART 공시 재무제표의 연간 사업보고서(현재 버전)에서만 계산하며 ${fsDivLabel} 기준입니다. 분·반기 보고서는 지표 계산에 쓰지 않고, 필요한 계정이 없으면 값 없이 사유를 표시합니다.`}
        level="info"
        title="공시 원문 기반 지표"
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
                setReportId(null);
              }}
              value={activeSymbol ?? ""}
            >
              {stocks.map((instrument) => (
                <option key={instrument.symbol} value={instrument.symbol}>
                  {instrument.name} {instrument.symbol}
                </option>
              ))}
            </select>
          </label>
          <fieldset aria-label="재무제표 기준" className="control-group">
            {FS_DIVS.map((entry) => (
              <button
                aria-pressed={entry.key === fsDiv}
                key={entry.key}
                onClick={() => {
                  setFsDiv(entry.key);
                  setReportId(null);
                }}
                type="button"
              >
                {entry.label}
              </button>
            ))}
          </fieldset>
        </div>

        <KpiGrid columns={7} label="재무 지표 KPI">
          <CoordinateCell
            coord="A1"
            label="매출액 (원)"
            sub={basisSub}
            value={koreanAmountOrEmpty(figureAmount(latest, "revenue"))}
          />
          <CoordinateCell
            coord="A2"
            label="영업이익 (원)"
            value={koreanAmountOrEmpty(figureAmount(latest, "operating_income"))}
          />
          <CoordinateCell
            coord="A3"
            label="당기순이익 (원)"
            value={koreanAmountOrEmpty(figureAmount(latest, "net_income"))}
          />
          <CoordinateCell
            coord="A4"
            label="영업이익률"
            sub={operatingMargin?.formula}
            value={percentText(operatingMargin)}
          />
          <CoordinateCell
            coord="A5"
            label="ROE (지배주주)"
            sub={roe?.unavailable_reason == null ? roe?.formula : "지배주주 계정 없음"}
            value={percentText(roe)}
          />
          <CoordinateCell coord="A6" label="부채비율" value={percentText(debtRatio)} />
          <CoordinateCell
            coord="A7"
            label="매출액증가율"
            tone={signTone(revenueGrowth)}
            value={percentText(revenueGrowth)}
          />
        </KpiGrid>

        <div className="board">
          <div className="board__main">
            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">B1</span> 실적 추이
                </h2>
                <StatusBadge kind="neutral" label={`${fsDivLabel} · 연간`} />
              </div>
              <div className="card__body">
                {indicatorsQuery.isError ? (
                  <p className="inline-error" role="alert">
                    지표를 불러오지 못했습니다.
                    <button
                      className="retry-button"
                      onClick={() => {
                        void indicatorsQuery.refetch();
                      }}
                      type="button"
                    >
                      다시 시도
                    </button>
                  </p>
                ) : years.length === 0 ? (
                  <p className="card__note">수집된 연간 사업보고서가 없습니다.</p>
                ) : (
                  <FigureBars years={years.map(toFigureYear)} />
                )}
              </div>
              <div className="card__note">
                단위 원 · 출처 DART {fsDivLabel} 사업보고서 · 금액은 원문 그대로입니다
              </div>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">B2</span> 재무제표
                </h2>
                {selectedReport !== undefined && (
                  <StatusBadge kind="accent" label={`접수번호 ${selectedReport.rcept_no}`} />
                )}
              </div>
              <div className="card__body">
                <div className="control-row">
                  <label>
                    <span className="cell__coord">보고서 </span>
                    <select
                      aria-label="보고서 선택"
                      className="symbol-select"
                      onChange={(event) => {
                        setReportId(event.target.value);
                      }}
                      value={selectedReport?.report_id ?? ""}
                    >
                      {annualReports.map((report) => (
                        <option key={report.report_id} value={report.report_id}>
                          {report.bsns_year} 사업보고서 · {fsDivLabel}
                        </option>
                      ))}
                    </select>
                  </label>
                  <fieldset aria-label="재무제표 구분" className="control-group">
                    {STATEMENT_TABS.map((entry) => (
                      <button
                        aria-pressed={entry.key === statement}
                        key={entry.key}
                        onClick={() => {
                          setStatement(entry.key);
                        }}
                        type="button"
                      >
                        {entry.label}
                      </button>
                    ))}
                  </fieldset>
                </div>
                <StatementLines reportId={selectedReport?.report_id} statement={statement} />
              </div>
              <div className="card__note">
                금액 단위 원 · 출처 DART 원문 라인 · 파생·환산하지 않습니다
              </div>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">C1</span> 연도별 지표
                </h2>
              </div>
              <div className="card__body">
                {years.length === 0 ? (
                  <p className="card__note">지표를 계산할 연간 보고서가 없습니다.</p>
                ) : (
                  <table className="grid-table grid-table--stack">
                    <thead>
                      <tr>
                        <th scope="col">지표</th>
                        {years.map((year) => (
                          <th key={year.bsns_year} scope="col">
                            {year.bsns_year}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {categories.flatMap((group) =>
                        group.keys.map((key, index) => {
                          const rows = years.map((year) => indicatorOf(year, key));
                          const sample = rows.find((entry) => entry !== undefined);
                          return (
                            <tr key={key}>
                              <td className="is-name" data-label="지표" title={sample?.formula}>
                                {index === 0 && (
                                  <span className="cell__coord">
                                    {CATEGORY_LABEL[group.category]}{" "}
                                  </span>
                                )}
                                {sample?.name ?? key}
                              </td>
                              {rows.map((indicator, yearIndex) => (
                                <td
                                  data-label={String(years[yearIndex]?.bsns_year ?? "")}
                                  key={years[yearIndex]?.bsns_year}
                                  title={
                                    indicator?.unavailable_reason == null
                                      ? indicator?.formula
                                      : UNAVAILABLE_LABEL[indicator.unavailable_reason]
                                  }
                                >
                                  {percentText(indicator)}
                                </td>
                              ))}
                            </tr>
                          );
                        }),
                      )}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                단위 % · 수식은 각 셀 도움말에 표시 · 값이 없는 지표는 사유와 함께 비웁니다
              </div>
            </section>
          </div>

          <div className="board__aside">
            <section className="card card--empty">
              <div className="card__head">
                <h2>
                  <span className="card__coord">C2</span> 가치 지표
                </h2>
              </div>
              <div className="card__body">
                PER·PBR·EPS·BPS는 상장주식수 정규화 수집 후 제공합니다. 산식·기준일을 증명할 수 없는
                외부 계산값은 쓰지 않습니다.
              </div>
            </section>

            <section className="card">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D1</span> 근거 공시
                </h2>
              </div>
              <div className="card__body">
                {years.length === 0 ? (
                  <p className="card__note">근거로 쓸 보고서가 없습니다.</p>
                ) : (
                  <dl className="fact-list">
                    {years.map((year) => (
                      <div key={year.rcept_no}>
                        <dt>{year.bsns_year} 사업보고서</dt>
                        <dd>
                          {year.rcept_no} · v{year.version}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
              <div className="card__note">출처 DART · 정정 공시는 새 버전으로 반영됩니다</div>
            </section>

            <section className="card card--empty">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D2</span> 수급
                </h2>
              </div>
              <div className="card__body">
                외국인·기관 수급은 아직 수집하지 않습니다. 4단계 후속 작업에서 제공됩니다.
              </div>
            </section>

            <section className="card card--empty">
              <div className="card__head">
                <h2>
                  <span className="card__coord">D3</span> 공시 연결
                </h2>
              </div>
              <div className="card__body">
                배당 외 주요 공시 연결은 아직 만들지 않았습니다. 4단계 후속 작업에서 제공됩니다.
              </div>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
