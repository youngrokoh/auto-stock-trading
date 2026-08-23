import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  fetchDisclosures,
  fetchFinancialIndicators,
  fetchFinancialReportDetail,
  fetchFinancialReports,
} from "../api/fundamentals";
import { fetchInstruments, fetchInvestorFlows } from "../api/market-data";
import { AppShell } from "../components/app-shell";
import { CoordinateCell, KpiGrid } from "../components/coordinate-cell";
import type { FigureYear } from "../components/figure-bars";
import { FigureBars } from "../components/figure-bars";
import { SafetyBanner } from "../components/safety-banner";
import { StatusBadge } from "../components/status-badge";
import {
  decimalToNumber,
  formatDecimal,
  formatKoreanAmount,
  formatKstDateTime,
  formatSignedDecimal,
} from "../lib/format";
import type { AnnualIndicators, FinancialIndicator, ValuationItem } from "../lib/fundamentals";

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

const DISCLOSURE_TYPE_LABEL: Readonly<Record<string, string>> = {
  A: "정기",
  B: "주요사항",
  D: "지분",
  I: "거래소",
};

const netTone = (value: number): string | undefined => {
  if (value > 0) {
    return "is-up";
  }
  return value < 0 ? "is-down" : undefined;
};

const UNAVAILABLE_LABEL: Readonly<Record<string, string>> = {
  AMBIGUOUS_ACCOUNT: "계정 중복",
  MISSING_ACCOUNT: "계정 없음",
  MISSING_AMOUNT: "금액 없음",
  MISSING_QUOTE: "시세 없음",
  MISSING_SHARE_COUNT: "주식수 없음",
  // 금융업은 매출액·영업이익 표준계정을 쓰지 않는다. '계정 없음'과 원인이 다르다.
  SECTOR_ACCOUNT_BASIS: "업종 회계기준 미해당",
  ZERO_DENOMINATOR: "분모 0",
};

const valuationItemText = (item: ValuationItem): string => {
  if (item.value === null) {
    return item.unavailable_reason === null
      ? "—"
      : `— (${UNAVAILABLE_LABEL[item.unavailable_reason] ?? item.unavailable_reason})`;
  }
  if (item.unit === "ratio") {
    return `${formatDecimal(item.value)}배`;
  }
  return item.key === "market_cap"
    ? `${formatKoreanAmount(item.value)}원`
    : `${formatDecimal(item.value)}원`;
};

const figureAmount = (year: AnnualIndicators | undefined, key: string): string | null =>
  year?.figures.find((figure) => figure.key === key)?.amount ?? null;

const RESOLUTION_LABEL: Readonly<Record<string, string>> = {
  identity_verified: "분해 항등식으로 확정",
  standard_difference: "표준계정 차감으로 복원",
};

/**
 * 표준 계정에서 직접 읽지 않은 입력의 설명. 과거 보고서는 같은 계정을 표준 ID 없이 이름만으로
 * 적는 경우가 많아 산술로 복원한다. 복원한 값을 표준 태깅된 값처럼 보여주면 안 된다.
 */
const restoredNote = (indicator: FinancialIndicator | undefined): string | undefined => {
  const restored = indicator?.inputs.filter((input) => input.resolution !== "standard_account");
  if (restored === undefined || restored.length === 0) {
    return undefined;
  }
  const parts = restored.map(
    (input) => `${input.name}: ${RESOLUTION_LABEL[input.resolution] ?? input.resolution}`,
  );
  return [...new Set(parts)].join(" · ");
};

const indicatorOf = (
  year: AnnualIndicators | undefined,
  key: string,
): FinancialIndicator | undefined => year?.indicators.find((entry) => entry.key === key);

const percentText = (indicator: FinancialIndicator | undefined): string =>
  indicator?.value == null ? "—" : `${formatDecimal(indicator.value)}%`;

/** 값이 없으면 수식 대신 사유를 보여준다. 줄표만 두면 수집 실패로 읽힌다. */
const indicatorSub = (indicator: FinancialIndicator | undefined): string | undefined => {
  if (indicator === undefined) {
    return undefined;
  }
  if (indicator.unavailable_reason === null) {
    return indicator.formula;
  }
  return UNAVAILABLE_LABEL[indicator.unavailable_reason] ?? indicator.unavailable_reason;
};

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
  const flowsQuery = useQuery({
    enabled: activeSymbol !== null,
    queryFn: () => fetchInvestorFlows(activeSymbol ?? "", 8),
    queryKey: ["investor-flows", activeSymbol],
    retry: false,
  });
  const disclosuresQuery = useQuery({
    enabled: activeSymbol !== null,
    queryFn: () => fetchDisclosures(activeSymbol ?? "", 8),
    queryKey: ["disclosures", activeSymbol],
    retry: false,
  });

  const years = indicatorsQuery.data?.years ?? [];
  const latest = years.at(-1);
  const valuation = indicatorsQuery.data?.valuation ?? null;
  const flows = flowsQuery.data?.flows ?? [];
  const disclosureItems = disclosuresQuery.data?.disclosures ?? [];
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

  // 업종 회계상 해당하지 않는 지표는 표에서 줄표가 되므로 수집 실패로 오해하기 쉽다.
  // 어떤 지표가 왜 비었는지 카드 주석에 이름으로 밝힌다(표 폭은 건드리지 않는다).
  const sectorBasisIndicators = (latest?.indicators ?? [])
    .filter((indicator) => indicator.unavailable_reason === "SECTOR_ACCOUNT_BASIS")
    .map((indicator) => indicator.name);

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
            sub={indicatorSub(operatingMargin)}
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
            sub={indicatorSub(revenueGrowth)}
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
                              {rows.map((indicator, yearIndex) => {
                                const restored = restoredNote(indicator);
                                const reason = indicator?.unavailable_reason;
                                const base =
                                  reason == null ? indicator?.formula : UNAVAILABLE_LABEL[reason];
                                return (
                                  <td
                                    data-label={String(years[yearIndex]?.bsns_year ?? "")}
                                    key={years[yearIndex]?.bsns_year}
                                    title={
                                      restored === undefined ? base : `${base ?? ""} — ${restored}`
                                    }
                                  >
                                    {percentText(indicator)}
                                    {restored !== undefined && indicator?.value != null && (
                                      <span className="cell__coord" title={restored}>
                                        {" †"}
                                      </span>
                                    )}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        }),
                      )}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                단위 % · 수식은 각 셀 도움말에 표시 · 값이 없는 지표는 사유와 함께 비웁니다 ·{" †"}
                는 표준 계정이 없어 산술로 복원한 입력이 있다는 표시입니다(계정명으로 값을 고르지
                않습니다)
                {sectorBasisIndicators.length > 0 && (
                  <>
                    {" · "}
                    {sectorBasisIndicators.join(" · ")}은 이 발행사의 업종 회계기준에 해당하지
                    않습니다(매출액·영업이익 표준계정 미사용)
                  </>
                )}
              </div>
            </section>
          </div>

          <div className="board__aside">
            <section className={valuation === null ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">C2</span> 가치 지표
                </h2>
              </div>
              <div className="card__body">
                {valuation === null ? (
                  "가치지표를 계산할 연간 보고서가 없습니다."
                ) : (
                  <dl className="fact-list">
                    {valuation.items.map((item) => (
                      <div key={item.key}>
                        <dt title={item.formula}>{item.name}</dt>
                        <dd>{valuationItemText(item)}</dd>
                      </div>
                    ))}
                    <div>
                      <dt>가격 기준</dt>
                      <dd>
                        {valuation.price === null
                          ? "저장된 시세 없음"
                          : `${formatDecimal(valuation.price.price)}원 · ${formatKstDateTime(valuation.price.as_of)}`}
                      </dd>
                    </div>
                    <div>
                      <dt>상장주식수</dt>
                      <dd>
                        {valuation.share_count === null
                          ? "저장된 주식수 없음"
                          : `${formatDecimal(String(valuation.share_count.share_count))}주`}
                      </dd>
                    </div>
                    <div>
                      <dt>재무 기준</dt>
                      <dd>
                        {valuation.report.bsns_year} 사업보고서 · {valuation.report.rcept_no}
                      </dd>
                    </div>
                  </dl>
                )}
              </div>
              <div className="card__note">
                산식은 각 항목 도움말에 표시 · BPS·PBR은 우선주 반영 설계 확정 후 제공합니다
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

            <section className={flows.length === 0 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">D2</span> 수급
                </h2>
              </div>
              <div className="card__body">
                {flows.length === 0 ? (
                  flowsQuery.isError ? (
                    "수급 데이터를 불러오지 못했습니다."
                  ) : (
                    "수집된 투자자별 매매 데이터가 없습니다."
                  )
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
                          <td className={netTone(flow.foreign_net_quantity)}>
                            {formatSignedDecimal(String(flow.foreign_net_quantity))}
                          </td>
                          <td className={netTone(flow.institution_net_quantity)}>
                            {formatSignedDecimal(String(flow.institution_net_quantity))}
                          </td>
                          <td className={netTone(flow.individual_net_quantity)}>
                            {formatSignedDecimal(String(flow.individual_net_quantity))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="card__note">
                순매수 수량(주) · 출처 KIS 일별 확정치(당일 제외) · 기타 주체가 없어 합계는 0이
                아닙니다
              </div>
            </section>

            <section className={disclosureItems.length === 0 ? "card card--empty" : "card"}>
              <div className="card__head">
                <h2>
                  <span className="card__coord">D3</span> 공시 연결
                </h2>
              </div>
              <div className="card__body">
                {disclosureItems.length === 0 ? (
                  disclosuresQuery.isError ? (
                    "공시 목록을 불러오지 못했습니다."
                  ) : (
                    "수집된 공시가 없습니다."
                  )
                ) : (
                  <ul className="disclosure-list">
                    {disclosureItems.map((entry) => (
                      <li key={entry.rcept_no}>
                        <span className="disclosure-list__meta">
                          {entry.rcept_dt} · {DISCLOSURE_TYPE_LABEL[entry.disclosure_type]} ·{" "}
                          {entry.flr_nm}
                        </span>
                        <a
                          href={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${entry.rcept_no}`}
                          rel="noopener noreferrer"
                          target="_blank"
                        >
                          {entry.report_nm}
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="card__note">
                출처 DART 최근 1년 목록(정기·주요사항·지분·거래소) · 제목을 누르면 DART 원문으로
                이동합니다
              </div>
            </section>
          </div>
        </div>
      </div>
    </AppShell>
  );
};
