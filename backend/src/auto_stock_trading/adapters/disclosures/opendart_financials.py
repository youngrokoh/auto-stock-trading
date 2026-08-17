import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, ClassVar, Final, final

from pydantic import BaseModel, ConfigDict, ValidationError

from auto_stock_trading.adapters.disclosures.dart_cash_dividend import DartContractError
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialRawResponse,
    FinancialReport,
    FinancialReportObservation,
    FinancialStatementLine,
    FsDivision,
    ReportCode,
    StatementDivision,
)

if TYPE_CHECKING:
    from auto_stock_trading.adapters.disclosures.opendart_http import DartHttpClient

DART_FINANCIALS_ENDPOINT = "/api/fnlttSinglAcntAll.json"
_STATUS_OK: Final = "000"
_STATUS_NO_DATA: Final = "013"
_UNMAPPED_ACCOUNT: Final = "-표준계정코드 미사용-"
_EMPTY_VALUES: Final = ("", "-")


class DartFinancialRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    rcept_no: str
    reprt_code: str
    bsns_year: str
    corp_code: str
    sj_div: str
    account_id: str = _UNMAPPED_ACCOUNT
    account_nm: str
    account_detail: str = "-"
    ord: str
    currency: str
    thstrm_nm: str
    thstrm_amount: str = ""
    frmtrm_nm: str = ""
    frmtrm_amount: str = ""
    bfefrmtrm_nm: str = ""
    bfefrmtrm_amount: str = ""


class DartFinancialsResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    status: str
    message: str
    list: tuple[DartFinancialRow, ...] = ()


@dataclass(frozen=True, slots=True)
class FinancialStatementTarget:
    symbol: str
    corp_code: str


@final
class DartFinancialStatementAdapter:
    def __init__(self, client: DartHttpClient, target: FinancialStatementTarget) -> None:
        self._client = client
        self._target = target

    @property
    def symbol(self) -> str:
        return self._target.symbol

    async def fetch_report(
        self,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
    ) -> FinancialReportObservation:
        payload = await self._client.fetch_text(
            DART_FINANCIALS_ENDPOINT,
            {
                "corp_code": self._target.corp_code,
                "bsns_year": str(bsns_year),
                "reprt_code": reprt_code.value,
                "fs_div": fs_div.value,
            },
        )
        received_at = datetime.now(UTC)
        raw = FinancialRawResponse(
            endpoint=DART_FINANCIALS_ENDPOINT,
            request_fingerprint=(
                f"dart:financials:{self._target.corp_code}:{bsns_year}"
                f":{reprt_code.value}:{fs_div.value}"
            ),
            received_at=received_at,
            payload_json=payload,
        )
        response = _parse_response(payload)
        if response.status == _STATUS_NO_DATA:
            return FinancialReportObservation(raw=raw, report=None)
        if response.status != _STATUS_OK or not response.list:
            message = f"DART financial statement status was not acceptable: {response.status}"
            raise DartContractError(message)
        report = self._normalized_report(bsns_year, reprt_code, fs_div, response, received_at)
        return FinancialReportObservation(raw=raw, report=report)

    async def close(self) -> None:
        await self._client.close()

    def _normalized_report(
        self,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
        response: DartFinancialsResponse,
        received_at: datetime,
    ) -> FinancialReport:
        receipt_numbers = {row.rcept_no for row in response.list}
        currencies = {row.currency for row in response.list}
        if len(receipt_numbers) != 1 or len(currencies) != 1:
            message = "DART financial statement rows must share one receipt number and currency"
            raise DartContractError(message)
        return FinancialReport(
            symbol=self._target.symbol,
            corp_code=self._target.corp_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            rcept_no=next(iter(receipt_numbers)),
            currency=next(iter(currencies)),
            received_at=received_at,
            lines=tuple(
                _normalized_line(seq, row) for seq, row in enumerate(response.list, start=1)
            ),
        )


def _parse_response(payload: str) -> DartFinancialsResponse:
    try:
        return DartFinancialsResponse.model_validate(json.loads(payload))
    except (json.JSONDecodeError, ValidationError) as error:
        message = "DART financial statement response did not match the expected contract"
        raise DartContractError(message) from error


def _normalized_line(line_seq: int, row: DartFinancialRow) -> FinancialStatementLine:
    try:
        sj_div = StatementDivision(row.sj_div)
        ord_value = int(row.ord)
    except ValueError as error:
        message = "DART financial statement row had an unknown division or order"
        raise DartContractError(message) from error
    return FinancialStatementLine(
        line_seq=line_seq,
        sj_div=sj_div,
        account_id=None if row.account_id in (_UNMAPPED_ACCOUNT, "") else row.account_id,
        account_nm=row.account_nm,
        account_detail=None if row.account_detail in _EMPTY_VALUES else row.account_detail,
        ord=ord_value,
        thstrm_nm=row.thstrm_nm,
        thstrm_amount=_amount(row.thstrm_amount),
        frmtrm_nm=row.frmtrm_nm or None,
        frmtrm_amount=_amount(row.frmtrm_amount),
        bfefrmtrm_nm=row.bfefrmtrm_nm or None,
        bfefrmtrm_amount=_amount(row.bfefrmtrm_amount),
    )


def _amount(value: str) -> Decimal | None:
    stripped = value.strip()
    if stripped in _EMPTY_VALUES:
        return None
    try:
        return Decimal(stripped.replace(",", ""))
    except InvalidOperation as error:
        message = "DART financial statement amount was not a number"
        raise DartContractError(message) from error
