from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, ClassVar, Final, final, override
from zoneinfo import ZoneInfo

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarRawResponse,
    CalendarSessionKey,
    CalendarSessionRange,
    CalendarSource,
    ClosedMarketSession,
    MarketSessionType,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
)

KRX_OTP_ENDPOINT: Final = "/contents/COM/GenerateOTP.jspx"
KRX_MARKET_CALENDAR_DATA_ENDPOINT: Final = "/contents/GLB/99/GLB99000001.jspx"
_CALENDAR_BLD: Final = "GLB/05/0501/0501110000/glb0501110000_01"
_CALENDAR_PAGE: Final = "/contents/GLB/05/0501/0501110000/GLB0501110000.jsp"
_SOURCE_REFERENCE: Final = "KRX GLB0501110000 + GLB0602010201T1"
_SEOUL: Final = ZoneInfo("Asia/Seoul")
_USER_AGENT: Final = "auto-stock-trading/0.1 (market-calendar integration)"
_HTTP_ERROR_STATUS: Final = 400
_SATURDAY_WEEKDAY: Final = 5


class _KrxContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class KrxHolidayRow(_KrxContract):
    calnd_dd: date
    dy_tp_cd: str
    calnd_dd_dy: date
    kr_dy_tp: str
    holdy_eng_nm: str


class KrxHolidayResponse(_KrxContract):
    block1: Annotated[tuple[KrxHolidayRow, ...], Field(min_length=1)]


@final
@dataclass(frozen=True, slots=True)
class KrxTransportError(Exception):
    endpoint: str
    status_code: int | None

    @override
    def __str__(self) -> str:
        suffix = "network failure" if self.status_code is None else f"HTTP {self.status_code}"
        return f"KRX request failed at {self.endpoint}: {suffix}"


@final
@dataclass(frozen=True, slots=True)
class KrxContractError(Exception):
    message: str = "KRX market calendar response did not match the expected contract"

    @override
    def __str__(self) -> str:
        return self.message


@final
class KrxHttpClient:
    def __init__(self, client: httpx2.AsyncClient) -> None:
        self._client = client

    async def fetch_holidays(self, year: int) -> CalendarRawResponse:
        otp = await self._request(
            "GET",
            KRX_OTP_ENDPOINT,
            params={"name": "form", "bld": _CALENDAR_BLD},
        )
        code = otp.text.strip()
        if not code:
            raise KrxContractError
        response = await self._request(
            "POST",
            KRX_MARKET_CALENDAR_DATA_ENDPOINT,
            data={
                "code": code,
                "search_bas_yy": str(year),
                "gridTp": "KRX",
                "pagePath": _CALENDAR_PAGE,
            },
        )
        return CalendarRawResponse(
            endpoint=KRX_MARKET_CALENDAR_DATA_ENDPOINT,
            request_fingerprint=f"krx:market-calendar:{year}",
            received_at=datetime.now(UTC),
            payload_json=response.text,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> httpx2.Response:
        try:
            response = await self._client.request(
                method,
                endpoint,
                params=params,
                data=data,
                headers={"Referer": f"{self._client.base_url}{_CALENDAR_PAGE}"},
            )
        except httpx2.HTTPError as error:
            raise KrxTransportError(endpoint, None) from error
        if response.status_code >= _HTTP_ERROR_STATUS:
            raise KrxTransportError(endpoint, response.status_code)
        return response


def create_krx_http_client(base_url: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0),
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )


@final
class KrxMarketCalendarAdapter:
    def __init__(self, client: KrxHttpClient) -> None:
        self._client = client

    async def fetch_sessions(
        self,
        query: CalendarSessionRange,
    ) -> tuple[CalendarObservation, ...]:
        if query.country != "KR" or query.exchange != "XKRX":
            message = "KRX market calendar adapter only supports KR/XKRX"
            raise ValueError(message)
        if query.session_type is not MarketSessionType.REGULAR:
            message = "KRX market calendar adapter only supports regular sessions"
            raise ValueError(message)
        raw_by_year: dict[int, CalendarRawResponse] = {}
        holidays_by_year: dict[int, dict[date, str | None]] = {}
        for year in range(query.start_date.year, query.end_date.year + 1):
            raw = await self._client.fetch_holidays(year)
            raw_by_year[year] = raw
            holidays_by_year[year] = _holidays_from(raw, year)
        observations: list[CalendarObservation] = []
        trading_date = query.start_date
        while trading_date <= query.end_date:
            raw = raw_by_year[trading_date.year]
            observations.append(
                _observation(
                    query,
                    trading_date,
                    holidays_by_year[trading_date.year],
                    raw,
                )
            )
            trading_date += timedelta(days=1)
        return tuple(observations)

    async def close(self) -> None:
        await self._client.close()


def _holidays_from(raw: CalendarRawResponse, year: int) -> dict[date, str | None]:
    try:
        response = KrxHolidayResponse.model_validate_json(raw.payload_json)
    except ValidationError as error:
        raise KrxContractError from error
    holidays: dict[date, str | None] = {}
    for item in response.block1:
        if item.calnd_dd.year != year or item.calnd_dd != item.calnd_dd_dy:
            raise KrxContractError
        if item.calnd_dd in holidays:
            raise KrxContractError
        holidays[item.calnd_dd] = item.holdy_eng_nm or None
    return holidays


def _observation(
    query: CalendarSessionRange,
    trading_date: date,
    holidays: dict[date, str | None],
    raw: CalendarRawResponse,
) -> CalendarObservation:
    key = CalendarSessionKey(query.country, query.exchange, trading_date, query.session_type)
    reason = holidays.get(trading_date)
    if trading_date in holidays:
        session = ClosedMarketSession(key, reason)
    elif trading_date.weekday() >= _SATURDAY_WEEKDAY:
        session = ClosedMarketSession(key, trading_date.strftime("%A"))
    else:
        session = OpenMarketSession(
            key,
            SessionWindow(
                datetime.combine(trading_date, time(9), _SEOUL).astimezone(UTC),
                datetime.combine(trading_date, time(15, 30), _SEOUL).astimezone(UTC),
            ),
        )
    return CalendarObservation(
        session=session,
        exchange_timezone="Asia/Seoul",
        source=CalendarSource(
            "KRX",
            _SOURCE_REFERENCE,
            raw.received_at.astimezone(_SEOUL).date(),
        ),
        raw_response=raw,
        verification=PendingVerification(),
    )
