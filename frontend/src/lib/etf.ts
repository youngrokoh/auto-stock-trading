import { z } from "zod";

const decimal = z.string().regex(/^-?\d+(\.\d+)?([Ee][+-]?\d+)?$/);
const nullableDecimal = decimal.nullable();
const isoDate = z.iso.date();
const isoDateTime = z.iso.datetime();

const etfSnapshotSchema = z.strictObject({
  as_of: isoDateTime,
  change_percent: decimal,
  currency: z.string().min(1),
  divergence_rate: decimal,
  index_name: z.string().min(1),
  listed_shares: z.number().int(),
  listing_date: isoDate.nullable(),
  manager: z.string().min(1),
  nav: decimal,
  net_asset_total: z.number().int(),
  previous_volume: z.number().int(),
  price: decimal,
  received_at: isoDateTime,
  tracking_error: decimal,
  tracking_multiple: decimal,
  volume: z.number().int(),
});

const etfListingSchema = z.strictObject({
  isin: z.string().min(1),
  name: z.string().min(1),
  snapshot: etfSnapshotSchema.nullable(),
  symbol: z.string().min(1),
});

const etfsSchema = z.strictObject({
  etfs: z.array(etfListingSchema).readonly(),
  master_source: z.string().min(1),
  net_asset_unit: z.literal("hundred_million_krw"),
  source: z.string().min(1),
});

const distributionYieldSchema = z.strictObject({
  distribution_count: z.number().int(),
  distribution_total: nullableDecimal,
  formula: z.string().min(1),
  unavailable_reason: z
    .enum(["MISSING_SNAPSHOT", "MISSING_DISTRIBUTIONS", "ZERO_PRICE"])
    .nullable(),
  value: nullableDecimal,
  window_end: isoDate.nullable(),
  window_start: isoDate.nullable(),
});

const etfDetailSchema = z.strictObject({
  distribution_yield: distributionYieldSchema,
  isin: z.string().min(1),
  master_source: z.string().min(1),
  name: z.string().min(1),
  net_asset_unit: z.literal("hundred_million_krw"),
  snapshot: etfSnapshotSchema.nullable(),
  source: z.string().min(1),
  symbol: z.string().min(1),
});

export type EtfSnapshot = z.infer<typeof etfSnapshotSchema>;
export type EtfListing = z.infer<typeof etfListingSchema>;
export type Etfs = z.infer<typeof etfsSchema>;
export type EtfDetail = z.infer<typeof etfDetailSchema>;

export const parseEtfs = (input: unknown): Etfs => etfsSchema.parse(input);
export const parseEtfDetail = (input: unknown): EtfDetail => etfDetailSchema.parse(input);
