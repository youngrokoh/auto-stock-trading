from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, override

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID


class ReportCode(StrEnum):
    FIRST_QUARTER = "11013"
    HALF_YEAR = "11012"
    THIRD_QUARTER = "11014"
    ANNUAL = "11011"


class FsDivision(StrEnum):
    CONSOLIDATED = "CFS"
    SEPARATE = "OFS"


class StatementDivision(StrEnum):
    BALANCE_SHEET = "BS"
    INCOME_STATEMENT = "IS"
    COMPREHENSIVE_INCOME = "CIS"
    CASH_FLOW = "CF"
    EQUITY_CHANGES = "SCE"


_LEGACY_IFRS_PREFIX: Final = "ifrs_"
_IFRS_PREFIX: Final = "ifrs-full_"


def normalized_account_id(account_id: str | None) -> str | None:
    """계정 ID를 현행 접두로 맞춘다.

    실측(2026-08-23): 2018년 이전 보고서는 `ifrs_`, 2019년 이후는 `ifrs-full_` 접두를 쓴다.
    IFRS 택소노미 개정으로 접두만 바뀌었고 계정의 의미는 같다. `dart_` 접두는 변하지 않았다.
    """
    if account_id is None:
        return None
    if account_id.startswith(_LEGACY_IFRS_PREFIX):
        return _IFRS_PREFIX + account_id[len(_LEGACY_IFRS_PREFIX) :]
    return account_id


class FinancialReportInvariant(StrEnum):
    VALIDITY = "corrected financial report evidence must have a newer receipt number"


@dataclass(frozen=True, slots=True)
class InvalidFinancialReportError(Exception):
    invariant: FinancialReportInvariant

    @override
    def __str__(self) -> str:
        return self.invariant.value


@dataclass(frozen=True, slots=True)
class FinancialStatementLine:
    line_seq: int
    sj_div: StatementDivision
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


@dataclass(frozen=True, slots=True)
class FinancialReport:
    symbol: str
    corp_code: str
    bsns_year: int
    reprt_code: ReportCode
    fs_div: FsDivision
    rcept_no: str
    currency: str
    received_at: datetime
    lines: tuple[FinancialStatementLine, ...]


@dataclass(frozen=True, slots=True)
class FinancialRawResponse:
    endpoint: str
    request_fingerprint: str
    received_at: datetime
    payload_json: str


@dataclass(frozen=True, slots=True)
class FinancialReportObservation:
    raw: FinancialRawResponse
    report: FinancialReport | None


@dataclass(frozen=True, slots=True)
class VersionedFinancialReport:
    report_id: UUID
    symbol: str
    corp_code: str
    bsns_year: int
    reprt_code: ReportCode
    fs_div: FsDivision
    rcept_no: str
    currency: str
    received_at: datetime
    version: int
    valid_from: datetime
    superseded_at: datetime | None
