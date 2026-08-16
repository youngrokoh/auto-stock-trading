from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, Final, final
from zoneinfo import ZoneInfo

from auto_stock_trading.adapters.brokers.kis_contracts import KisHolidayResponse
from auto_stock_trading.adapters.brokers.kis_mapping import KisContractError, parse_response
from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarRawResponse,
    CalendarSource,
    ClosedMarketSession,
    ConfirmedVerification,
    MarketCalendarRecord,
    OpenMarketSession,
    SessionWindow,
    ShortenedMarketSession,
    calendar_session_key,
)
from auto_stock_trading.domain.market_data.models import BrokerOperation

if TYPE_CHECKING:
    from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient, KisRawResponse

KIS_MARKET_CALENDAR_ENDPOINT: Final = "/uapi/domestic-stock/v1/quotations/chk-holiday"
_KIS_MARKET_CALENDAR_TRANSACTION_ID: Final = "CTCA0903R"
_SEOUL: Final = ZoneInfo("Asia/Seoul")


@final
class KisMarketCalendarVerifier:
    def __init__(self, client: KisHttpClient) -> None:
        self._client = client

    async def verify(self, current: MarketCalendarRecord) -> CalendarObservation:
        trading_date = calendar_session_key(current.session).trading_date
        raw = await self._client.get(
            endpoint=KIS_MARKET_CALENDAR_ENDPOINT,
            transaction_id=_KIS_MARKET_CALENDAR_TRANSACTION_ID,
            params={
                "BASS_DT": trading_date.strftime("%Y%m%d"),
                "CTX_AREA_FK": "",
                "CTX_AREA_NK": "",
            },
            request_fingerprint=f"kis:market-calendar:{trading_date}",
        )
        response = parse_response(
            raw,
            KisHolidayResponse,
            BrokerOperation.MARKET_CALENDAR,
        )
        matches = tuple(item for item in response.output if _kis_date(item.bass_dt) == trading_date)
        if len(matches) != 1:
            raise KisContractError(BrokerOperation.MARKET_CALENDAR)
        item = matches[0]
        session = _verified_session(current, kis_open=item.opnd_yn == "Y")
        return CalendarObservation(
            session=session,
            exchange_timezone=current.exchange_timezone,
            source=CalendarSource("KIS", KIS_MARKET_CALENDAR_ENDPOINT, trading_date),
            raw_response=_calendar_raw(raw),
            verification=ConfirmedVerification(raw.received_at),
        )

    async def close(self) -> None:
        await self._client.close()


def _verified_session(
    current: MarketCalendarRecord,
    *,
    kis_open: bool,
) -> OpenMarketSession | ClosedMarketSession | ShortenedMarketSession:
    session = current.session
    if kis_open and isinstance(session, OpenMarketSession | ShortenedMarketSession):
        return session
    if not kis_open and isinstance(session, ClosedMarketSession):
        return session
    key = calendar_session_key(session)
    if kis_open:
        trading_date = key.trading_date
        return OpenMarketSession(
            key,
            SessionWindow(
                datetime.combine(trading_date, time(9), _SEOUL).astimezone(UTC),
                datetime.combine(trading_date, time(15, 30), _SEOUL).astimezone(UTC),
            ),
        )
    return ClosedMarketSession(key, "KIS reported the market closed")


def _calendar_raw(raw: KisRawResponse) -> CalendarRawResponse:
    return CalendarRawResponse(
        endpoint=raw.endpoint,
        request_fingerprint=raw.request_fingerprint,
        received_at=raw.received_at,
        payload_json=raw.payload_json,
    )


def _kis_date(value: str) -> date:
    return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
