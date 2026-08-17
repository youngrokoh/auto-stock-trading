from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final, override
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from auto_stock_trading.domain.market_data.listed_shares import ListedShareCount
from auto_stock_trading.domain.market_data.minute_bars import MinuteBar
from auto_stock_trading.domain.market_data.models import (
    BrokerOperation,
    DailyBar,
    Instrument,
    InstrumentTarget,
    Quote,
    RawBrokerResponse,
)

if TYPE_CHECKING:
    from auto_stock_trading.adapters.brokers.kis_contracts import (
        KisDailyBarOutput,
        KisDailyBarsResponse,
        KisInstrumentResponse,
        KisMinuteBarOutput,
        KisQuoteResponse,
    )
    from auto_stock_trading.adapters.brokers.kis_http import KisRawResponse

KIS_SOURCE = "KIS"
_SEOUL: Final = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True, slots=True)
class KisApiError(Exception):
    operation: BrokerOperation
    code: str
    message: str

    @override
    def __str__(self) -> str:
        return f"KIS {self.operation.value} failed ({self.code}): {self.message}"


@dataclass(frozen=True, slots=True)
class KisContractError(Exception):
    operation: BrokerOperation

    @override
    def __str__(self) -> str:
        return f"KIS {self.operation.value} response did not match the expected contract"


def parse_response[ResponseT: BaseModel](
    raw: KisRawResponse,
    response_type: type[ResponseT],
    operation: BrokerOperation,
) -> ResponseT:
    try:
        response = response_type.model_validate_json(raw.payload_json)
    except ValidationError as error:
        raise KisContractError(operation) from error
    rt_cd = getattr(response, "rt_cd", "")
    if rt_cd != "0":
        raise KisApiError(
            operation,
            str(getattr(response, "msg_cd", "unknown")),
            str(getattr(response, "msg1", "KIS returned an error")),
        )
    return response


def instrument_from(
    target: InstrumentTarget,
    response: KisInstrumentResponse,
    received_at: datetime,
) -> Instrument:
    output = response.output
    listed_on = _date_or_none(output.scts_mket_lstg_dt or output.kosdaq_mket_lstg_dt)
    delisted_on = _date_or_none(
        output.lstg_abol_dt or output.scts_mket_lstg_abol_dt or output.kosdaq_mket_lstg_abol_dt
    )
    return Instrument(
        country="KR",
        exchange="XKRX",
        symbol=target.symbol,
        product_type=target.product_type,
        currency="KRW",
        name=output.prdt_name,
        english_name=output.prdt_eng_name or None,
        listed_on=listed_on,
        delisted_on=delisted_on,
        trading_status="suspended" if output.tr_stop_yn == "Y" else "active",
        source=KIS_SOURCE,
        source_as_of=received_at.astimezone(_SEOUL).date(),
    )


def instrument_from_daily_summary(
    target: InstrumentTarget,
    response: KisDailyBarsResponse,
    received_at: datetime,
) -> Instrument:
    return Instrument(
        country="KR",
        exchange="XKRX",
        symbol=target.symbol,
        product_type=target.product_type,
        currency="KRW",
        name=response.output1.hts_kor_isnm or target.symbol,
        english_name=None,
        listed_on=None,
        delisted_on=None,
        trading_status="active",
        source=KIS_SOURCE,
        source_as_of=received_at.astimezone(_SEOUL).date(),
    )


def quote_from(
    target: InstrumentTarget,
    response: KisQuoteResponse,
    received_at: datetime,
) -> Quote:
    output = response.output
    return Quote(
        symbol=target.symbol,
        price=_decimal(output.stck_prpr),
        open_price=_decimal(output.stck_oprc),
        high_price=_decimal(output.stck_hgpr),
        low_price=_decimal(output.stck_lwpr),
        previous_close=_decimal(output.stck_sdpr),
        change=_decimal(output.prdy_vrss),
        change_percent=_decimal(output.prdy_ctrt),
        volume=_integer(output.acml_vol),
        trading_value=_decimal(output.acml_tr_pbmn),
        currency="KRW",
        source=KIS_SOURCE,
        as_of=received_at,
        received_at=received_at,
    )


def listed_shares_from(
    target: InstrumentTarget,
    response: KisQuoteResponse,
    received_at: datetime,
) -> ListedShareCount:
    return ListedShareCount(
        symbol=target.symbol,
        share_count=_integer(response.output.lstn_stcn),
        source=KIS_SOURCE,
        as_of=received_at,
        received_at=received_at,
    )


def bar_from(
    target: InstrumentTarget,
    output: KisDailyBarOutput,
    received_at: datetime,
) -> DailyBar:
    return DailyBar(
        symbol=target.symbol,
        trading_date=_kis_date(output.stck_bsop_date),
        open_price=_decimal(output.stck_oprc),
        high_price=_decimal(output.stck_hgpr),
        low_price=_decimal(output.stck_lwpr),
        close_price=_decimal(output.stck_clpr),
        volume=_integer(output.acml_vol),
        trading_value=_decimal(output.acml_tr_pbmn),
        adjusted=False,
        correction_code=output.revl_issu_reas or ("modified" if output.mod_yn == "Y" else None),
        split_ratio=_decimal_or_none(output.prtt_rate),
        source=KIS_SOURCE,
        received_at=received_at,
    )


def minute_bar_from(
    target: InstrumentTarget,
    output: KisMinuteBarOutput,
    received_at: datetime,
) -> MinuteBar:
    trading_date = _kis_date(output.stck_bsop_date)
    label = output.stck_cntg_hour
    bar_started_at = datetime.combine(
        trading_date,
        time(int(label[:2]), int(label[2:4]), int(label[4:6])),
        _SEOUL,
    ).astimezone(UTC)
    return MinuteBar(
        symbol=target.symbol,
        trading_date=trading_date,
        bar_started_at=bar_started_at,
        open_price=_decimal(output.stck_oprc),
        high_price=_decimal(output.stck_hgpr),
        low_price=_decimal(output.stck_lwpr),
        close_price=_decimal(output.stck_prpr),
        volume=_integer(output.cntg_vol),
        cumulative_trading_value=_decimal(output.acml_tr_pbmn),
        source=KIS_SOURCE,
        received_at=received_at,
    )


def raw_from(operation: BrokerOperation, response: KisRawResponse) -> RawBrokerResponse:
    return RawBrokerResponse(
        operation=operation,
        endpoint=response.endpoint,
        request_fingerprint=response.request_fingerprint,
        received_at=response.received_at,
        payload_json=response.payload_json,
    )


def _date_or_none(value: str) -> date | None:
    return _kis_date(value) if value else None


def _kis_date(value: str) -> date:
    return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise KisContractError(BrokerOperation.DAILY_BARS) from error


def _decimal_or_none(value: str) -> Decimal | None:
    return _decimal(value) if value else None


def _integer(value: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise KisContractError(BrokerOperation.DAILY_BARS) from error
