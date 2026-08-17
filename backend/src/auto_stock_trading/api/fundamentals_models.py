from datetime import datetime
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
