import {
  type AccountSnapshots,
  type Automation,
  type NotificationStatus,
  parseAccountSnapshots,
  parseAutomation,
  parseNotificationStatus,
  parseOrders,
  parseRiskLimits,
  type RiskLimits,
  type TradingOrders,
} from "../lib/trading";

const fetchJson = async (path: string): Promise<unknown> => {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`모의매매 API 오류 (${String(response.status)})`);
  }
  return (await response.json()) as unknown;
};

export const fetchAutomation = async (): Promise<Automation> =>
  parseAutomation(await fetchJson("/api/trading/automation"));

export const fetchAccountSnapshots = async (limit: number): Promise<AccountSnapshots> =>
  parseAccountSnapshots(await fetchJson(`/api/trading/account-snapshots?limit=${String(limit)}`));

export const fetchTradingOrders = async (limit: number): Promise<TradingOrders> =>
  parseOrders(await fetchJson(`/api/trading/orders?limit=${String(limit)}`));

export const fetchRiskLimits = async (): Promise<RiskLimits> =>
  parseRiskLimits(await fetchJson("/api/trading/risk-limits"));

export const fetchNotificationStatus = async (): Promise<NotificationStatus> =>
  parseNotificationStatus(await fetchJson("/api/trading/notifications"));
