import {
  type BacktestEquity,
  type BacktestRuns,
  type BacktestTrades,
  parseBacktestEquity,
  parseBacktestRuns,
  parseBacktestTrades,
} from "../lib/backtests";

const fetchJson = async (path: string): Promise<unknown> => {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`백테스트 API 오류 (${String(response.status)})`);
  }
  return (await response.json()) as unknown;
};

export const fetchBacktestRuns = async (): Promise<BacktestRuns> =>
  parseBacktestRuns(await fetchJson("/api/backtests?limit=50"));

export const fetchBacktestTrades = async (runId: string): Promise<BacktestTrades> =>
  parseBacktestTrades(await fetchJson(`/api/backtests/${runId}/trades`));

export const fetchBacktestEquity = async (runId: string): Promise<BacktestEquity> =>
  parseBacktestEquity(await fetchJson(`/api/backtests/${runId}/equity`));
