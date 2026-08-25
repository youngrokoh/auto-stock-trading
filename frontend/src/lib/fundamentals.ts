import { z } from "zod";

const decimal = z.string().regex(/^-?\d+(\.\d+)?([Ee][+-]?\d+)?$/);
const nullableDecimal = decimal.nullable();
const isoDateTime = z.iso.datetime();

const statementDivision = z.enum(["BS", "IS", "CIS", "CF", "SCE"]);

const financialReportSchema = z.strictObject({
  bsns_year: z.number().int(),
  corp_code: z.string().min(1),
  currency: z.string().min(1),
  fs_div: z.enum(["CFS", "OFS"]),
  rcept_no: z.string().min(1),
  received_at: isoDateTime,
  report_id: z.uuid(),
  reprt_code: z.enum(["11011", "11012", "11013", "11014"]),
  superseded_at: isoDateTime.nullable(),
  symbol: z.string().min(1),
  valid_from: isoDateTime,
  version: z.number().int().positive(),
});

const financialReportsSchema = z.strictObject({
  reports: z.array(financialReportSchema).readonly(),
  source: z.string().min(1),
  symbol: z.string().min(1),
});

const statementLineSchema = z.strictObject({
  account_detail: z.string().nullable(),
  account_id: z.string().nullable(),
  account_nm: z.string().min(1),
  bfefrmtrm_amount: nullableDecimal,
  bfefrmtrm_nm: z.string().nullable(),
  frmtrm_amount: nullableDecimal,
  frmtrm_nm: z.string().nullable(),
  line_seq: z.number().int().positive(),
  ord: z.number().int(),
  sj_div: statementDivision,
  thstrm_amount: nullableDecimal,
  thstrm_nm: z.string().min(1),
});

const financialReportDetailSchema = z.strictObject({
  lines: z.array(statementLineSchema).readonly(),
  report: financialReportSchema,
  source: z.string().min(1),
});

const accountResolution = z.enum(["standard_account", "identity_verified", "standard_difference"]);

const indicatorInputSchema = z.strictObject({
  account_id: z.string().min(1),
  amount: nullableDecimal,
  name: z.string().min(1),
  period: z.enum(["thstrm", "frmtrm"]),
  resolution: accountResolution,
  sj_div: statementDivision,
});

const indicatorSchema = z.strictObject({
  category: z.enum(["growth", "profitability", "stability"]),
  formula: z.string().min(1),
  inputs: z.array(indicatorInputSchema).readonly(),
  key: z.string().min(1),
  name: z.string().min(1),
  unavailable_reason: z
    .enum([
      "MISSING_ACCOUNT",
      "AMBIGUOUS_ACCOUNT",
      "MISSING_AMOUNT",
      "ZERO_DENOMINATOR",
      "SECTOR_ACCOUNT_BASIS",
    ])
    .nullable(),
  unit: z.literal("percent"),
  value: nullableDecimal,
});

const financialFigureSchema = z.strictObject({
  account_id: z.string().min(1),
  amount: nullableDecimal,
  key: z.string().min(1),
  name: z.string().min(1),
  resolution: accountResolution,
  sj_div: statementDivision,
});

const annualIndicatorsSchema = z.strictObject({
  bsns_year: z.number().int(),
  currency: z.string().min(1),
  figures: z.array(financialFigureSchema).readonly(),
  fs_div: z.enum(["CFS", "OFS"]),
  indicators: z.array(indicatorSchema).readonly(),
  rcept_no: z.string().min(1),
  reprt_code: z.enum(["11011", "11012", "11013", "11014"]),
  version: z.number().int().positive(),
});

const unavailableReason = z.enum([
  "MISSING_ACCOUNT",
  "AMBIGUOUS_ACCOUNT",
  "MISSING_AMOUNT",
  "ZERO_DENOMINATOR",
  "MISSING_QUOTE",
  "MISSING_SHARE_COUNT",
  "SECTOR_ACCOUNT_BASIS",
  "MISSING_CLASS_QUOTE",
  "PREFERRED_ALLOCATION_REQUIRED",
]);

const valuationItemSchema = z.strictObject({
  formula: z.string().min(1),
  key: z.string().min(1),
  name: z.string().min(1),
  resolution: accountResolution,
  unavailable_reason: unavailableReason.nullable(),
  unit: z.enum(["krw", "ratio"]),
  value: nullableDecimal,
});

/** 상장 클래스 내역. 거래가 없는 우선주도 기준시각이 드러나야 한다. */
const shareClassSchema = z.strictObject({
  as_of: isoDateTime.nullable(),
  class_kind: z.enum(["common", "preferred"]),
  market_cap: nullableDecimal,
  name: z.string().min(1),
  price: nullableDecimal,
  share_count: z.number().int().nullable(),
  share_count_as_of: isoDateTime.nullable(),
  symbol: z.string().min(1),
  volume: z.number().int().nullable(),
});

const valuationSchema = z.strictObject({
  items: z.array(valuationItemSchema).readonly(),
  price: z
    .strictObject({
      as_of: isoDateTime,
      price: decimal,
      source: z.string().min(1),
    })
    .nullable(),
  report: z.strictObject({
    bsns_year: z.number().int(),
    fs_div: z.enum(["CFS", "OFS"]),
    rcept_no: z.string().min(1),
    reprt_code: z.enum(["11011", "11012", "11013", "11014"]),
    version: z.number().int().positive(),
  }),
  share_count: z
    .strictObject({
      as_of: isoDateTime,
      share_count: z.number().int().positive(),
      source: z.string().min(1),
      version: z.number().int().positive(),
    })
    .nullable(),
  share_classes: z.array(shareClassSchema).readonly(),
});

const financialIndicatorsSchema = z.strictObject({
  fs_div: z.enum(["CFS", "OFS"]),
  source: z.string().min(1),
  symbol: z.string().min(1),
  valuation: valuationSchema.nullable(),
  years: z.array(annualIndicatorsSchema).readonly(),
});

const disclosureSchema = z.strictObject({
  disclosure_type: z.enum(["A", "B", "D", "I"]),
  flr_nm: z.string().min(1),
  rcept_dt: z.iso.date(),
  rcept_no: z.string().min(1),
  received_at: isoDateTime,
  report_nm: z.string().min(1),
});

const disclosuresSchema = z.strictObject({
  disclosures: z.array(disclosureSchema).readonly(),
  source: z.string().min(1),
  symbol: z.string().min(1),
});

export type FinancialReport = z.infer<typeof financialReportSchema>;
export type FinancialReports = z.infer<typeof financialReportsSchema>;
export type FinancialStatementLine = z.infer<typeof statementLineSchema>;
export type FinancialReportDetail = z.infer<typeof financialReportDetailSchema>;
export type FinancialIndicator = z.infer<typeof indicatorSchema>;
export type FinancialFigure = z.infer<typeof financialFigureSchema>;
export type AnnualIndicators = z.infer<typeof annualIndicatorsSchema>;
export type FinancialValuation = z.infer<typeof valuationSchema>;
export type ValuationItem = z.infer<typeof valuationItemSchema>;
export type ShareClassEntry = z.infer<typeof shareClassSchema>;
export type FinancialIndicators = z.infer<typeof financialIndicatorsSchema>;
export type Disclosure = z.infer<typeof disclosureSchema>;
export type Disclosures = z.infer<typeof disclosuresSchema>;

export const parseFinancialReports = (input: unknown): FinancialReports =>
  financialReportsSchema.parse(input);
export const parseFinancialReportDetail = (input: unknown): FinancialReportDetail =>
  financialReportDetailSchema.parse(input);
export const parseFinancialIndicators = (input: unknown): FinancialIndicators =>
  financialIndicatorsSchema.parse(input);
export const parseDisclosures = (input: unknown): Disclosures => disclosuresSchema.parse(input);

/** 공시 유형 코드의 표시 이름. 두 화면이 같은 말을 쓰도록 여기 하나만 둔다. */
const DISCLOSURE_TYPE_LABELS: Readonly<Record<string, string>> = {
  A: "정기",
  B: "주요사항",
  D: "지분",
  I: "거래소",
};

export const disclosureTypeLabel = (disclosureType: string): string =>
  DISCLOSURE_TYPE_LABELS[disclosureType] ?? disclosureType;
