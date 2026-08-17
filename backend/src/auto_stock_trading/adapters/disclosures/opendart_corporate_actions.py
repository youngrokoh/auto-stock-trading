import base64
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, ClassVar, Final, final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from auto_stock_trading.adapters.disclosures.dart_cash_dividend import (
    DartCashDividendNotice,
    DartContractError,
    parse_cash_dividend_document,
)
from auto_stock_trading.adapters.disclosures.opendart_http import (
    DART_DOCUMENT_ENDPOINT,
    DART_LIST_ENDPOINT,
    DartHttpClient,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionBundle,
    CorporateActionLifecycle,
    CorporateActionObservation,
    CorporateActionQuality,
    CorporateActionRawResponse,
    CorporateActionType,
    TimePrecision,
)

_DIVIDEND_REPORT_NAME: Final = "현금ㆍ현물배당결정"
_ALLOWED_REPORT_PREFIXES: Final = ("", "[기재정정]", "[첨부정정]", "[첨부추가]")
_STATUS_OK: Final = "000"
_STATUS_NO_DATA: Final = "013"
_PAGE_COUNT: Final = "100"
_VIEWER_URL: Final = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
_SOURCE: Final = "DART"
_CURRENCY: Final = "KRW"


class _DartContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class DartListStatus(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    status: str
    message: str


class DartListEntry(_DartContract):
    corp_cls: str
    corp_name: str
    corp_code: str
    stock_code: str
    report_nm: str
    rcept_no: str
    flr_nm: str
    rcept_dt: str
    rm: str


class DartListPage(_DartContract):
    status: str
    message: str
    page_no: int
    page_count: int
    total_count: int
    total_page: int
    entries: Annotated[tuple[DartListEntry, ...], Field(alias="list")]


@final
@dataclass(frozen=True, slots=True)
class DartDividendTarget:
    symbol: str
    corp_code: str


@final
class DartCorporateActionAdapter:
    def __init__(self, client: DartHttpClient, target: DartDividendTarget) -> None:
        self._client = client
        self._target = target

    @property
    def source_name(self) -> str:
        return _SOURCE

    @property
    def symbol(self) -> str:
        return self._target.symbol

    async def fetch_corporate_actions(
        self,
        start_date: date,
        end_date: date,
    ) -> CorporateActionBundle:
        target = self._target
        entries, list_raws = await self._list_disclosures(target, start_date, end_date)
        dividends = sorted(
            (entry for entry in entries if _is_dividend_decision(entry, target)),
            key=lambda entry: (entry.rcept_dt, entry.rcept_no),
        )
        observations = tuple([await self._observe(entry) for entry in dividends])
        return CorporateActionBundle(
            source=_SOURCE,
            symbol=target.symbol,
            observations=observations,
            supporting_raw_responses=list_raws,
            collected_at=datetime.now(UTC),
        )

    async def close(self) -> None:
        await self._client.close()

    async def _list_disclosures(
        self,
        target: DartDividendTarget,
        start_date: date,
        end_date: date,
    ) -> tuple[tuple[DartListEntry, ...], tuple[CorporateActionRawResponse, ...]]:
        entries: list[DartListEntry] = []
        raws: list[CorporateActionRawResponse] = []
        page_no = 1
        while True:
            params = {
                "corp_code": target.corp_code,
                "bgn_de": start_date.strftime("%Y%m%d"),
                "end_de": end_date.strftime("%Y%m%d"),
                "page_no": str(page_no),
                "page_count": _PAGE_COUNT,
            }
            payload = await self._client.fetch_text(DART_LIST_ENDPOINT, params)
            raws.append(
                CorporateActionRawResponse(
                    endpoint=DART_LIST_ENDPOINT,
                    request_fingerprint=(
                        f"dart:list:{target.corp_code}"
                        f":{params['bgn_de']}:{params['end_de']}:{page_no}"
                    ),
                    received_at=datetime.now(UTC),
                    payload_json=payload,
                )
            )
            page = _validated_page(payload)
            if page is None:
                break
            entries.extend(page.entries)
            if page.page_no >= page.total_page:
                break
            page_no = page.page_no + 1
        return tuple(entries), tuple(raws)

    async def _observe(self, entry: DartListEntry) -> CorporateActionObservation:
        content = await self._client.fetch_bytes(
            DART_DOCUMENT_ENDPOINT,
            {"rcept_no": entry.rcept_no},
        )
        received_at = datetime.now(UTC)
        filename, document = _unpack_document(entry.rcept_no, content)
        notice = parse_cash_dividend_document(_decode_document(entry.rcept_no, document))
        raw = CorporateActionRawResponse(
            endpoint=DART_DOCUMENT_ENDPOINT,
            request_fingerprint=f"dart:document:{entry.rcept_no}",
            received_at=received_at,
            payload_json=json.dumps(
                {
                    "rcept_no": entry.rcept_no,
                    "filename": filename,
                    "document_base64": base64.b64encode(document).decode("ascii"),
                },
                ensure_ascii=False,
            ),
        )
        return CorporateActionObservation(
            action=_cash_dividend_action(entry, notice, received_at),
            raw_response=raw,
        )


def _validated_page(payload: str) -> DartListPage | None:
    try:
        status = DartListStatus.model_validate_json(payload)
    except ValidationError as error:
        message = "DART list response is not a valid status document"
        raise DartContractError(message) from error
    if status.status == _STATUS_NO_DATA:
        return None
    if status.status != _STATUS_OK:
        message = f"DART list status {status.status}: {status.message}"
        raise DartContractError(message)
    try:
        return DartListPage.model_validate_json(payload)
    except ValidationError as error:
        message = "DART list response did not match the expected contract"
        raise DartContractError(message) from error


def _is_dividend_decision(entry: DartListEntry, target: DartDividendTarget) -> bool:
    report_name = entry.report_nm.replace(" ", "")
    if not report_name.endswith(_DIVIDEND_REPORT_NAME):
        return False
    if entry.stock_code != target.symbol or entry.corp_code != target.corp_code:
        message = f"DART list entry does not match the target: {entry.rcept_no}"
        raise DartContractError(message)
    prefix = report_name.removesuffix(_DIVIDEND_REPORT_NAME)
    if prefix not in _ALLOWED_REPORT_PREFIXES:
        message = f"unsupported dividend report prefix: {entry.report_nm}"
        raise DartContractError(message)
    return True


def _unpack_document(rcept_no: str, content: bytes) -> tuple[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) != 1:
                message = f"expected one document in DART archive {rcept_no}, found {len(members)}"
                raise DartContractError(message)
            return members[0].filename, archive.read(members[0])
    except zipfile.BadZipFile as error:
        message = f"DART document {rcept_no} is not a valid archive"
        raise DartContractError(message) from error


def _decode_document(rcept_no: str, document: bytes) -> str:
    for encoding in ("cp949", "utf-8"):
        try:
            return document.decode(encoding)
        except UnicodeDecodeError:
            continue
    message = f"DART document {rcept_no} has an unsupported text encoding"
    raise DartContractError(message)


def _cash_dividend_action(
    entry: DartListEntry,
    notice: DartCashDividendNotice,
    received_at: datetime,
) -> CorporateAction:
    return CorporateAction(
        action_type=CorporateActionType.CASH_DIVIDEND,
        lifecycle=CorporateActionLifecycle.ANNOUNCED,
        quality=CorporateActionQuality.PENDING,
        announced_at=None,
        announcement_date=_receipt_date(entry.rcept_dt),
        time_precision=TimePrecision.DATE,
        ex_date=None,
        effective_date=None,
        record_date=notice.record_date,
        payment_date=notice.payment_date,
        share_multiplier=None,
        cash_amount=notice.per_share_common,
        currency=_CURRENCY,
        subscription_price=None,
        related_instrument_id=None,
        source=_SOURCE,
        source_event_id=entry.rcept_no,
        source_reference=_VIEWER_URL.format(rcept_no=entry.rcept_no),
        available_at=received_at,
        received_at=received_at,
    )


def _receipt_date(rcept_dt: str) -> date:
    try:
        return datetime.strptime(rcept_dt, "%Y%m%d").replace(tzinfo=UTC).date()
    except ValueError as error:
        message = f"invalid DART receipt date: {rcept_dt}"
        raise DartContractError(message) from error
