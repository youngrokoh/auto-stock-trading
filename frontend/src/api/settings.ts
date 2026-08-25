import { type CostRules, parseCostRules } from "../lib/settings";

export const fetchCostRules = async (): Promise<CostRules> => {
  const response = await fetch("/api/settings/cost-rules", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`설정 API 오류 (${String(response.status)})`);
  }
  return parseCostRules((await response.json()) as unknown);
};
