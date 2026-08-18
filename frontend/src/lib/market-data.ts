import { z } from "zod";

const decimal = z.string().regex(/^-?\d+(\.\d+)?([Ee][+-]?\d+)?$/);
const nullableDecimal = decimal.nullable();
const isoDate = z.iso.date();
const isoDateTime = z.iso.datetime();

const instrumentSchema = z.strictObject({
  country: z.string().min(1),
  currency: z.string().min(1),
  delisted_on: isoDate.nullable(),
  english_name: z.string().nullable(),
  exchange: z.string().min(1),
  listed_on: isoDate.nullable(),
  name: z.string().min(1),
  product_type: z.enum(["stock", "etf"]),
  source: z.string().min(1),
  source_as_of: isoDate,
  symbol: z.string().min(1),
  trading_status: z.string().min(1),
});

const instrumentsSchema = z.strictObject({
  instruments: z.array(instrumentSchema).readonly(),
});

const quoteSchema = z.strictObject({
  as_of: isoDateTime,
  change: decimal,
  change_percent: decimal,
  currency: z.string().min(1),
  high_price: decimal,
  low_price: decimal,
  open_price: decimal,
  previous_close: decimal,
  price: decimal,
  received_at: isoDateTime,
  source: z.string().min(1),
  symbol: z.string().min(1),
  trading_value: decimal,
  volume: z.number().int().nonnegative(),
});

const dailyBarSchema = z.strictObject({
  adjusted: z.literal(false),
  close_price: decimal,
  confirmed_at: isoDateTime.nullable(),
  correction_code: z.string().nullable(),
  finality: z.enum(["pending", "confirmed"]),
  high_price: decimal,
  low_price: decimal,
  open_price: decimal,
  received_at: isoDateTime,
  source: z.string().min(1),
  split_ratio: nullableDecimal,
  trading_date: isoDate,
  trading_value: decimal,
  valid_from: isoDateTime,
  version: z.number().int().positive(),
  volume: z.number().int().nonnegative(),
});

const dailyBarsSchema = z.strictObject({
  bars: z.array(dailyBarSchema).readonly(),
  end_date: isoDate.nullable(),
  interval: z.literal("1d"),
  source: z.string().nullable(),
  start_date: isoDate.nullable(),
  symbol: z.string().min(1),
});

const corporateActionSchema = z.strictObject({
  action_key: z.uuid(),
  action_type: z.string().min(1),
  announced_at: isoDateTime.nullable(),
  announcement_date: isoDate,
  available_at: isoDateTime,
  cash_amount: nullableDecimal,
  corporate_action_id: z.uuid(),
  currency: z.string().nullable(),
  effective_date: isoDate.nullable(),
  ex_date: isoDate.nullable(),
  lifecycle: z.enum(["announced", "confirmed", "cancelled"]),
  payment_date: isoDate.nullable(),
  quality: z.enum(["pending", "verified", "conflict", "unsupported"]),
  received_at: isoDateTime,
  record_date: isoDate.nullable(),
  related_instrument_id: z.uuid().nullable(),
  share_multiplier: nullableDecimal,
  source: z.string().min(1),
  source_event_id: z.string().min(1),
  source_reference: z.string().min(1),
  subscription_price: nullableDecimal,
  superseded_at: isoDateTime.nullable(),
  time_precision: z.enum(["date", "minute", "second"]),
  valid_from: isoDateTime,
  version: z.number().int().positive(),
});

const corporateActionsSchema = z.strictObject({
  actions: z.array(corporateActionSchema).readonly(),
  end_date: isoDate.nullable(),
  include_history: z.boolean(),
  knowledge_cutoff_at: isoDateTime.nullable(),
  start_date: isoDate.nullable(),
  symbol: z.string().min(1),
});

const investorFlowSchema = z.strictObject({
  foreign_net_quantity: z.number().int(),
  foreign_net_value: z.number().int(),
  individual_net_quantity: z.number().int(),
  individual_net_value: z.number().int(),
  institution_net_quantity: z.number().int(),
  institution_net_value: z.number().int(),
  received_at: isoDateTime,
  trading_date: isoDate,
  version: z.number().int().positive(),
});

const investorFlowsSchema = z.strictObject({
  flows: z.array(investorFlowSchema).readonly(),
  quantity_unit: z.literal("share"),
  source: z.string().min(1),
  symbol: z.string().min(1),
  value_unit: z.literal("million_krw"),
});

const adjustedDatasetSchema = z.strictObject({
  action_version_hash: z.string().min(1),
  algorithm_version: z.string().min(1),
  dataset_id: z.uuid(),
  failure_code: z.string().nullable(),
  generated_at: isoDateTime,
  input_bar_version_hash: z.string().min(1),
  interval: z.literal("1d"),
  knowledge_cutoff_at: isoDateTime,
  method: z.enum(["split_adjusted", "total_return"]),
  price_cutoff_date: isoDate,
  range_start: isoDate,
  status: z.string().min(1),
  superseded_at: isoDateTime.nullable(),
  symbol: z.string().min(1),
});

const adjustedDailyBarSchema = z.strictObject({
  close_price: decimal,
  high_price: decimal,
  low_price: decimal,
  open_price: decimal,
  price_factor: decimal,
  source: z.string().min(1),
  source_bar_id: z.uuid(),
  source_bar_version: z.number().int().positive(),
  trading_date: isoDate,
  trading_value: decimal,
  volume: z.number().int().nonnegative(),
  volume_factor: decimal,
});

const appliedCorporateActionSchema = z.strictObject({
  action_key: z.uuid(),
  action_version: z.number().int().positive(),
  corporate_action_id: z.uuid(),
  event_date: isoDate,
  event_price_factor: decimal,
  event_volume_factor: decimal,
  source: z.string().min(1),
});

const adjustedDailyBarsSchema = z.strictObject({
  applied_actions: z.array(appliedCorporateActionSchema).readonly(),
  bars: z.array(adjustedDailyBarSchema).readonly(),
  dataset: adjustedDatasetSchema,
});

export type Instrument = z.infer<typeof instrumentSchema>;
export type Instruments = z.infer<typeof instrumentsSchema>;
export type Quote = z.infer<typeof quoteSchema>;
export type DailyBar = z.infer<typeof dailyBarSchema>;
export type DailyBars = z.infer<typeof dailyBarsSchema>;
export type CorporateAction = z.infer<typeof corporateActionSchema>;
export type CorporateActions = z.infer<typeof corporateActionsSchema>;
export type InvestorFlow = z.infer<typeof investorFlowSchema>;
export type InvestorFlows = z.infer<typeof investorFlowsSchema>;
export type AdjustedDailyBar = z.infer<typeof adjustedDailyBarSchema>;
export type AdjustedDailyBars = z.infer<typeof adjustedDailyBarsSchema>;

export const parseInstruments = (input: unknown): Instruments => instrumentsSchema.parse(input);
export const parseQuote = (input: unknown): Quote => quoteSchema.parse(input);
export const parseDailyBars = (input: unknown): DailyBars => dailyBarsSchema.parse(input);
export const parseCorporateActions = (input: unknown): CorporateActions =>
  corporateActionsSchema.parse(input);
export const parseInvestorFlows = (input: unknown): InvestorFlows =>
  investorFlowsSchema.parse(input);
export const parseAdjustedDailyBars = (input: unknown): AdjustedDailyBars =>
  adjustedDailyBarsSchema.parse(input);
