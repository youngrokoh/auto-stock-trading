import {
  type CorporateActions,
  type DailyBars,
  type Instruments,
  parseCorporateActions,
  parseDailyBars,
  parseInstruments,
  parseQuote,
  type Quote,
} from "../lib/market-data";

const fetchJson = async (path: string): Promise<unknown> => {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`시장 데이터 API 오류 (${String(response.status)})`);
  }
  return (await response.json()) as unknown;
};

export const fetchInstruments = async (): Promise<Instruments> =>
  parseInstruments(await fetchJson("/api/market-data/instruments"));

export const fetchQuote = async (symbol: string): Promise<Quote> =>
  parseQuote(await fetchJson(`/api/market-data/instruments/${symbol}/quote`));

export const fetchDailyBars = async (symbol: string, startDate?: string): Promise<DailyBars> => {
  const query = startDate === undefined ? "" : `?start_date=${startDate}`;
  return parseDailyBars(
    await fetchJson(`/api/market-data/instruments/${symbol}/daily-bars${query}`),
  );
};

export const fetchCorporateActions = async (symbol: string): Promise<CorporateActions> =>
  parseCorporateActions(
    await fetchJson(`/api/market-data/instruments/${symbol}/corporate-actions`),
  );
