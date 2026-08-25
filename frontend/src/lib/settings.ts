import { z } from "zod";

const isoDate = z.iso.date();

const costRuleSchema = z.strictObject({
  current: z.boolean(),
  effective_from: isoDate,
  etf_slippage_rate: z.string().min(1),
  fee_rate: z.string().min(1),
  kosdaq_stock_sell_tax_rate: z.string().min(1),
  kospi_stock_sell_tax_rate: z.string().min(1),
  source: z.string().min(1),
  stock_slippage_rate: z.string().min(1),
  version: z.string().min(1),
});

const costRulesSchema = z.strictObject({
  evaluated_on: isoDate,
  rules: z.array(costRuleSchema).readonly(),
});

export type CostRule = z.infer<typeof costRuleSchema>;
export type CostRules = z.infer<typeof costRulesSchema>;

export const parseCostRules = (payload: unknown): CostRules => costRulesSchema.parse(payload);

/** 비율(0.0002)을 퍼센트 표시로. 정책 문서와 같은 단위로 읽히게 한다. */
export const ratePercent = (rate: string): string => {
  const value = Number.parseFloat(rate);
  if (Number.isNaN(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(3).replace(/0+$/, "").replace(/\.$/, "")}%`;
};

/** 근거가 연구 가정인지 공식 고시인지. 값과 신뢰 수준을 함께 읽게 한다. */
export const isResearchAssumption = (source: string): boolean => source.includes("연구 가정");
