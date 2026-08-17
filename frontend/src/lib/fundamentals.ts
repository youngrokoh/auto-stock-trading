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

const indicatorInputSchema = z.strictObject({
  account_id: z.string().min(1),
  amount: nullableDecimal,
  name: z.string().min(1),
  period: z.enum(["thstrm", "frmtrm"]),
  sj_div: statementDivision,
});

const indicatorSchema = z.strictObject({
  category: z.enum(["growth", "profitability", "stability"]),
  formula: z.string().min(1),
  inputs: z.array(indicatorInputSchema).readonly(),
  key: z.string().min(1),
  name: z.string().min(1),
  unavailable_reason: z
    .enum(["MISSING_ACCOUNT", "AMBIGUOUS_ACCOUNT", "MISSING_AMOUNT", "ZERO_DENOMINATOR"])
    .nullable(),
  unit: z.literal("percent"),
  value: nullableDecimal,
});

const financialFigureSchema = z.strictObject({
  account_id: z.string().min(1),
  amount: nullableDecimal,
  key: z.string().min(1),
  name: z.string().min(1),
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

const financialIndicatorsSchema = z.strictObject({
  fs_div: z.enum(["CFS", "OFS"]),
  source: z.string().min(1),
  symbol: z.string().min(1),
  years: z.array(annualIndicatorsSchema).readonly(),
});

export type FinancialReport = z.infer<typeof financialReportSchema>;
export type FinancialReports = z.infer<typeof financialReportsSchema>;
export type FinancialStatementLine = z.infer<typeof statementLineSchema>;
export type FinancialReportDetail = z.infer<typeof financialReportDetailSchema>;
export type FinancialIndicator = z.infer<typeof indicatorSchema>;
export type FinancialFigure = z.infer<typeof financialFigureSchema>;
export type AnnualIndicators = z.infer<typeof annualIndicatorsSchema>;
export type FinancialIndicators = z.infer<typeof financialIndicatorsSchema>;

export const parseFinancialReports = (input: unknown): FinancialReports =>
  financialReportsSchema.parse(input);
export const parseFinancialReportDetail = (input: unknown): FinancialReportDetail =>
  financialReportDetailSchema.parse(input);
export const parseFinancialIndicators = (input: unknown): FinancialIndicators =>
  financialIndicatorsSchema.parse(input);
