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

export type Instrument = z.infer<typeof instrumentSchema>;
export type Instruments = z.infer<typeof instrumentsSchema>;
export type Quote = z.infer<typeof quoteSchema>;
export type DailyBar = z.infer<typeof dailyBarSchema>;
export type DailyBars = z.infer<typeof dailyBarsSchema>;
export type CorporateAction = z.infer<typeof corporateActionSchema>;
export type CorporateActions = z.infer<typeof corporateActionsSchema>;

export const parseInstruments = (input: unknown): Instruments => instrumentsSchema.parse(input);
export const parseQuote = (input: unknown): Quote => quoteSchema.parse(input);
export const parseDailyBars = (input: unknown): DailyBars => dailyBarsSchema.parse(input);
export const parseCorporateActions = (input: unknown): CorporateActions =>
  corporateActionsSchema.parse(input);
