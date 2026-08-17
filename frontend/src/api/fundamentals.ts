import {
  type FinancialIndicators,
  type FinancialReportDetail,
  type FinancialReports,
  parseFinancialIndicators,
  parseFinancialReportDetail,
  parseFinancialReports,
} from "../lib/fundamentals";

const fetchJson = async (path: string): Promise<unknown> => {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`기업 분석 API 오류 (${String(response.status)})`);
  }
  return (await response.json()) as unknown;
};

export const fetchFinancialIndicators = async (
  symbol: string,
  fsDiv: "CFS" | "OFS",
): Promise<FinancialIndicators> =>
  parseFinancialIndicators(
    await fetchJson(`/api/fundamentals/instruments/${symbol}/indicators?fs_div=${fsDiv}`),
  );

export const fetchFinancialReports = async (symbol: string): Promise<FinancialReports> =>
  parseFinancialReports(
    await fetchJson(`/api/fundamentals/instruments/${symbol}/financial-reports`),
  );

export const fetchFinancialReportDetail = async (
  reportId: string,
): Promise<FinancialReportDetail> =>
  parseFinancialReportDetail(await fetchJson(`/api/fundamentals/financial-reports/${reportId}`));
