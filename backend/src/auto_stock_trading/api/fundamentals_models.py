from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FundamentalsResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class FinancialReportResponse(FundamentalsResponse):
    report_id: UUID
    symbol: str
    corp_code: str
    bsns_year: int
    reprt_code: str
    fs_div: str
    rcept_no: str
    currency: str
    received_at: datetime
    version: int
    valid_from: datetime
    superseded_at: datetime | None


class FinancialReportsResponse(FundamentalsResponse):
    symbol: str
    source: str = "DART"
    reports: tuple[FinancialReportResponse, ...]


class FinancialStatementLineResponse(FundamentalsResponse):
    line_seq: int
    sj_div: str
    account_id: str | None
    account_nm: str
    account_detail: str | None
    ord: int
    thstrm_nm: str
    thstrm_amount: Decimal | None
    frmtrm_nm: str | None
    frmtrm_amount: Decimal | None
    bfefrmtrm_nm: str | None
    bfefrmtrm_amount: Decimal | None


class FinancialReportDetailResponse(FundamentalsResponse):
    source: str = "DART"
    report: FinancialReportResponse
    lines: tuple[FinancialStatementLineResponse, ...]


class IndicatorInputResponse(FundamentalsResponse):
    name: str
    sj_div: str
    account_id: str
    period: str
    amount: Decimal | None
    # 금액을 표준계정에서 직접 읽었는지, 산술로 복원했는지(지표 계약 §복원 규칙).
    resolution: str


class IndicatorResponse(FundamentalsResponse):
    key: str
    name: str
    category: str
    unit: str = "percent"
    formula: str
    inputs: tuple[IndicatorInputResponse, ...]
    value: Decimal | None
    unavailable_reason: str | None


class FinancialFigureResponse(FundamentalsResponse):
    key: str
    name: str
    sj_div: str
    account_id: str
    amount: Decimal | None
    resolution: str


class AnnualIndicatorsResponse(FundamentalsResponse):
    bsns_year: int
    reprt_code: str
    fs_div: str
    rcept_no: str
    currency: str
    version: int
    figures: tuple[FinancialFigureResponse, ...]
    indicators: tuple[IndicatorResponse, ...]


class ValuationPriceBasisResponse(FundamentalsResponse):
    price: Decimal
    as_of: datetime
    source: str


class ValuationShareCountBasisResponse(FundamentalsResponse):
    share_count: int
    as_of: datetime
    source: str
    version: int


class ValuationReportBasisResponse(FundamentalsResponse):
    bsns_year: int
    reprt_code: str
    fs_div: str
    rcept_no: str
    version: int


class ValuationItemResponse(FundamentalsResponse):
    key: str
    name: str
    unit: str
    formula: str
    value: Decimal | None
    unavailable_reason: str | None


class ValuationResponse(FundamentalsResponse):
    price: ValuationPriceBasisResponse | None
    share_count: ValuationShareCountBasisResponse | None
    report: ValuationReportBasisResponse
    items: tuple[ValuationItemResponse, ...]


class FinancialIndicatorsResponse(FundamentalsResponse):
    symbol: str
    source: str = "DART"
    fs_div: str
    years: tuple[AnnualIndicatorsResponse, ...]
    valuation: ValuationResponse | None


class DisclosureResponse(FundamentalsResponse):
    rcept_no: str
    report_nm: str
    flr_nm: str
    rcept_dt: date
    disclosure_type: str
    received_at: datetime


class DisclosuresResponse(FundamentalsResponse):
    symbol: str
    source: str = "DART"
    disclosures: tuple[DisclosureResponse, ...]
