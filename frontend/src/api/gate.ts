import { type GateReadiness, parseGateReadiness } from "../lib/gate";

export const fetchGateReadiness = async (): Promise<GateReadiness> => {
  const response = await fetch("/api/gate/readiness", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`실전 전환 게이트 API 오류 (${String(response.status)})`);
  }
  return parseGateReadiness((await response.json()) as unknown);
};
