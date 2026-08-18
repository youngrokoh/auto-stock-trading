import { type EtfDetail, type Etfs, parseEtfDetail, parseEtfs } from "../lib/etf";

const fetchJson = async (path: string): Promise<unknown> => {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`ETF API 오류 (${String(response.status)})`);
  }
  return (await response.json()) as unknown;
};

export const fetchEtfs = async (): Promise<Etfs> =>
  parseEtfs(await fetchJson("/api/market-data/etfs"));

export const fetchEtfDetail = async (symbol: string): Promise<EtfDetail> =>
  parseEtfDetail(await fetchJson(`/api/market-data/etfs/${symbol}`));
