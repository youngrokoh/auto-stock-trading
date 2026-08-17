from datetime import datetime
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, final
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from auto_stock_trading.adapters.disclosures.dart_cash_dividend import DartContractError
from auto_stock_trading.adapters.disclosures.opendart_http import DART_LIST_ENDPOINT
from auto_stock_trading.domain.fundamentals.disclosures import (
    Disclosure,
    DisclosureBundle,
    DisclosurePage,
    DisclosureType,
)
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialRawResponse,
)

if TYPE_CHECKING:
    from datetime import date

    from auto_stock_trading.adapters.disclosures.opendart_http import DartHttpClient

_STATUS_OK: Final = "000"
_STATUS_NO_DATA: Final = "013"
_PAGE_COUNT: Final = "100"
_SEOUL: Final = ZoneInfo("Asia/Seoul")

DISCLOSURE_TYPES: Final = (
    DisclosureType.PERIODIC,
    DisclosureType.MATERIAL_EVENT,
    DisclosureType.OWNERSHIP,
    DisclosureType.EXCHANGE,
)


class _DartStatus(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    status: str
    message: str


class _DartDisclosureEntry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    corp_code: str
    rcept_no: str
    report_nm: str
    flr_nm: str
    rcept_dt: str


class _DartDisclosurePage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    status: str
    page_no: int
    total_page: int
    entries: Annotated[tuple[_DartDisclosureEntry, ...], Field(alias="list")]


@final
class DartDisclosureAdapter:
    def __init__(self, client: DartHttpClient, *, symbol: str, corp_code: str) -> None:
        self._client = client
        self._symbol = symbol
        self._corp_code = corp_code

    @property
    def symbol(self) -> str:
        return self._symbol

    async def fetch_disclosures(
        self,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> DisclosureBundle:
        pages: list[DisclosurePage] = []
        for disclosure_type in DISCLOSURE_TYPES:
            pages.extend(await self._fetch_type(disclosure_type, start_date, end_date, now))
        return DisclosureBundle(
            symbol=self._symbol,
            corp_code=self._corp_code,
            pages=tuple(pages),
            collected_at=now,
        )

    async def _fetch_type(
        self,
        disclosure_type: DisclosureType,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> tuple[DisclosurePage, ...]:
        pages: list[DisclosurePage] = []
        page_no = 1
        while True:
            params = {
                "corp_code": self._corp_code,
                "bgn_de": start_date.strftime("%Y%m%d"),
                "end_de": end_date.strftime("%Y%m%d"),
                "pblntf_ty": disclosure_type.value,
                "page_no": str(page_no),
                "page_count": _PAGE_COUNT,
            }
            payload = await self._client.fetch_text(DART_LIST_ENDPOINT, params)
            raw = FinancialRawResponse(
                endpoint=DART_LIST_ENDPOINT,
                request_fingerprint=(
                    f"dart:disclosures:{self._corp_code}:{disclosure_type.value}"
                    f":{params['bgn_de']}:{params['end_de']}:{page_no}"
                ),
                received_at=now,
                payload_json=payload,
            )
            page = _validated_page(payload)
            if page is None:
                pages.append(DisclosurePage(raw=raw, disclosures=()))
                break
            pages.append(
                DisclosurePage(
                    raw=raw,
                    disclosures=tuple(
                        self._disclosure_from(entry, disclosure_type, now) for entry in page.entries
                    ),
                )
            )
            if page.page_no >= page.total_page:
                break
            page_no = page.page_no + 1
        return tuple(pages)

    def _disclosure_from(
        self,
        entry: _DartDisclosureEntry,
        disclosure_type: DisclosureType,
        now: datetime,
    ) -> Disclosure:
        if entry.corp_code != self._corp_code:
            message = "DART disclosure entry corp_code does not match the requested company"
            raise DartContractError(message)
        return Disclosure(
            symbol=self._symbol,
            corp_code=entry.corp_code,
            rcept_no=entry.rcept_no,
            report_nm=entry.report_nm,
            filer_name=entry.flr_nm,
            receipt_date=datetime.strptime(entry.rcept_dt, "%Y%m%d").replace(tzinfo=_SEOUL).date(),
            disclosure_type=disclosure_type,
            received_at=now,
        )

    async def close(self) -> None:
        await self._client.close()


def _validated_page(payload: str) -> _DartDisclosurePage | None:
    try:
        status = _DartStatus.model_validate_json(payload)
    except ValidationError as error:
        message = "DART disclosure list response is not a valid status document"
        raise DartContractError(message) from error
    if status.status == _STATUS_NO_DATA:
        return None
    if status.status != _STATUS_OK:
        message = f"DART disclosure list returned status {status.status}"
        raise DartContractError(message)
    try:
        return _DartDisclosurePage.model_validate_json(payload)
    except ValidationError as error:
        message = "DART disclosure list page violates the expected contract"
        raise DartContractError(message) from error
