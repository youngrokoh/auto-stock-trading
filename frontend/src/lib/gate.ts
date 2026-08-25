import { z } from "zod";

const isoDateTime = z.iso.datetime();

const gateConditionSchema = z.strictObject({
  code: z.string().min(1),
  measured: z.string().nullable(),
  reason_code: z.string().nullable(),
  requirement: z.string().min(1),
  section: z.string().min(1),
  state: z.enum(["met", "not_met", "not_measurable"]),
  threshold: z.string().nullable(),
});

const gateLimitSchema = z.strictObject({
  code: z.string().min(1),
  item: z.string().min(1),
  value: z.string().min(1),
});

const gateReadinessSchema = z.strictObject({
  blocking_codes: z.array(z.string()).readonly(),
  conditions: z.array(gateConditionSchema).readonly(),
  environment: z.string().min(1),
  evaluated_at: isoDateTime,
  initial_limits: z.array(gateLimitSchema).readonly(),
  live_enabled: z.boolean(),
  passed: z.boolean(),
});

export type GateCondition = z.infer<typeof gateConditionSchema>;
export type GateLimit = z.infer<typeof gateLimitSchema>;
export type GateReadiness = z.infer<typeof gateReadinessSchema>;

export const parseGateReadiness = (payload: unknown): GateReadiness =>
  gateReadinessSchema.parse(payload);

/** 조건 상태의 한국어 표시. 화면과 감사 로그가 같은 코드를 쓰되 사람이 읽는 말은 따로 둔다. */
export const conditionLabel = (state: GateCondition["state"]): string => {
  if (state === "met") {
    return "충족";
  }
  if (state === "not_met") {
    return "미충족";
  }
  return "판정 불가";
};

/** 판정 불가는 경고도 위험도 아니다 — 사람이 확인해야 한다는 별개의 상태다. */
export const conditionTone = (state: GateCondition["state"]): "danger" | "normal" | "unknown" => {
  if (state === "met") {
    return "normal";
  }
  if (state === "not_met") {
    return "danger";
  }
  return "unknown";
};
