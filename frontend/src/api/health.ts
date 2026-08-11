import { parseReadiness, type Readiness } from "../lib/health";

export const fetchReadiness = async (): Promise<Readiness> => {
  const response = await fetch("/api/health/status", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error("상태 API에 연결할 수 없습니다.");
  }
  const payload: unknown = await response.json();
  return parseReadiness(payload);
};
