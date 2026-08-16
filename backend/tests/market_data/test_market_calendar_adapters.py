from datetime import UTC, date, datetime, time
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID
from zoneinfo import ZoneInfo

import anyio
import httpx2
from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_coordination import (
    InMemoryKisRequestCoordinator,
    KisCoordinationConfig,
)
from auto_stock_trading.adapters.brokers.kis_http import KisCredentials, KisHttpClient
from auto_stock_trading.adapters.brokers.kis_market_calendar import (
    KIS_MARKET_CALENDAR_ENDPOINT,
    KisMarketCalendarVerifier,
)
from auto_stock_trading.adapters.exchanges.krx_market_calendar import (
    KRX_MARKET_CALENDAR_DATA_ENDPOINT,
    KRX_OTP_ENDPOINT,
    KrxHttpClient,
    KrxMarketCalendarAdapter,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarSessionKey,
    CalendarSessionRange,
    CalendarSource,
    ClosedMarketSession,
    MarketCalendarRecord,
    MarketSessionStatus,
    MarketSessionType,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
    calendar_session_reason,
    calendar_session_status,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures"
_SEOUL = ZoneInfo("Asia/Seoul")


def test_krx_adapter_normalizes_official_holidays_weekends_and_regular_sessions() -> None:
    requests: list[httpx2.Request] = []

    def response_for(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path == KRX_OTP_ENDPOINT:
            return httpx2.Response(200, request=request, text="fixture-otp")
        if request.url.path == KRX_MARKET_CALENDAR_DATA_ENDPOINT:
            return httpx2.Response(
                200,
                request=request,
                text=(_FIXTURES / "krx" / "2026_holidays.json").read_text(encoding="utf-8"),
            )
        return httpx2.Response(404, request=request)

    async def run() -> tuple[CalendarObservation, ...]:
        client = httpx2.AsyncClient(
            base_url="https://global.krx.co.kr",
            transport=httpx2.MockTransport(response_for),
        )
        adapter = KrxMarketCalendarAdapter(KrxHttpClient(client))
        try:
            observations = await adapter.fetch_sessions(
                CalendarSessionRange(
                    "KR",
                    "XKRX",
                    date(2026, 8, 14),
                    date(2026, 8, 18),
                )
            )
        finally:
            await adapter.close()
        return observations

    observations = anyio.run(run)

    assert tuple(calendar_session_status(item.session) for item in observations) == (
        MarketSessionStatus.OPEN,
        MarketSessionStatus.CLOSED,
        MarketSessionStatus.CLOSED,
        MarketSessionStatus.CLOSED,
        MarketSessionStatus.OPEN,
    )
    assert calendar_session_reason(observations[1].session) == "Saturday"
    assert calendar_session_reason(observations[2].session) == "Sunday"
    assert calendar_session_reason(observations[3].session) == "Substitution Holiday"
    assert all(isinstance(item.verification, PendingVerification) for item in observations)
    assert len({item.raw_response for item in observations}) == 1
    assert tuple(request.url.path for request in requests) == (
        KRX_OTP_ENDPOINT,
        KRX_MARKET_CALENDAR_DATA_ENDPOINT,
    )
    assert parse_qs(requests[0].url.query.decode())["name"] == ["form"]
    post_data = parse_qs(requests[1].content.decode())
    assert post_data["code"] == ["fixture-otp"]
    assert post_data["search_bas_yy"] == ["2026"]


def test_kis_verifier_uses_open_day_flag_for_the_exact_trading_date() -> None:
    requests: list[httpx2.Request] = []

    def response_for(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "access_token": "fixture-access-token",
                    "token_type": "Bearer",
                    "expires_in": 86400,
                    "access_token_token_expired": "2099-08-14 12:00:00",
                },
            )
        requests.append(request)
        return httpx2.Response(
            200,
            request=request,
            text=(_FIXTURES / "kis" / "market_calendar.json").read_text(encoding="utf-8"),
        )

    async def run() -> tuple[CalendarObservation, CalendarObservation]:
        client = httpx2.AsyncClient(
            base_url="https://openapi.koreainvestment.com:9443",
            transport=httpx2.MockTransport(response_for),
        )
        http_client = KisHttpClient(
            client,
            KisCredentials(SecretStr("fixture-app-key"), SecretStr("fixture-app-secret")),
            InMemoryKisRequestCoordinator(KisCoordinationConfig(minimum_interval_seconds=0)),
        )
        verifier = KisMarketCalendarVerifier(http_client)
        try:
            closed = await verifier.verify(_record(date(2026, 8, 17), closed=True))
            opened = await verifier.verify(_record(date(2026, 8, 18), closed=False))
        finally:
            await verifier.close()
        return closed, opened

    closed, opened = anyio.run(run)

    assert isinstance(closed.session, ClosedMarketSession)
    assert isinstance(opened.session, OpenMarketSession)
    assert tuple(request.url.path for request in requests) == (
        KIS_MARKET_CALENDAR_ENDPOINT,
        KIS_MARKET_CALENDAR_ENDPOINT,
    )
    assert all(request.headers["tr_id"] == "CTCA0903R" for request in requests)
    assert tuple(parse_qs(request.url.query.decode())["BASS_DT"][0] for request in requests) == (
        "20260817",
        "20260818",
    )


def _record(trading_date: date, *, closed: bool) -> MarketCalendarRecord:
    key = _key(trading_date)
    session = (
        ClosedMarketSession(key, "KRX fixture holiday")
        if closed
        else OpenMarketSession(
            key,
            SessionWindow(
                datetime.combine(trading_date, time(9), _SEOUL).astimezone(UTC),
                datetime.combine(trading_date, time(15, 30), _SEOUL).astimezone(UTC),
            ),
        )
    )
    observed_at = datetime.combine(trading_date, time(6), _SEOUL).astimezone(UTC)
    return MarketCalendarRecord(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        session=session,
        exchange_timezone="Asia/Seoul",
        source=CalendarSource("KRX", "fixture", trading_date),
        received_at=observed_at,
        verification=PendingVerification(),
        version=1,
        valid_from=observed_at,
        superseded_at=None,
        raw_response_id=UUID("00000000-0000-0000-0000-000000000002"),
        created_at=observed_at,
        updated_at=observed_at,
    )


def _key(trading_date: date) -> CalendarSessionKey:
    return CalendarSessionKey("KR", "XKRX", trading_date, MarketSessionType.REGULAR)
