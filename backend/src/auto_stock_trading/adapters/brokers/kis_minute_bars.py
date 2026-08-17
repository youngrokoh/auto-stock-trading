from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Final, Protocol, final
from zoneinfo import ZoneInfo

from auto_stock_trading.adapters.brokers.kis_contracts import KisMinuteBarsResponse
from auto_stock_trading.adapters.brokers.kis_mapping import (
    minute_bar_from,
    parse_response,
    raw_from,
)
from auto_stock_trading.domain.market_data.minute_bars import (
    MinuteBar,
    MinuteBarBundle,
    MinuteBarPage,
)
from auto_stock_trading.domain.market_data.models import BrokerOperation

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient
    from auto_stock_trading.domain.market_data.calendar import SessionWindow
    from auto_stock_trading.domain.market_data.models import InstrumentTarget

MINUTE_BARS_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
_TRANSACTION_ID: Final = "FHKST03010200"
_SEOUL: Final = ZoneInfo("Asia/Seoul")
_MINUTE: Final = timedelta(minutes=1)
_MAX_PAGES: Final = 30


class MinuteBarSource(Protocol):
    async def fetch_minute_bars(
        self,
        target: InstrumentTarget,
        trading_date: date,
        window: SessionWindow,
        now: datetime,
    ) -> MinuteBarBundle: ...

    async def close(self) -> None: ...


@final
class KisMinuteBarAdapter:
    def __init__(self, client: KisHttpClient) -> None:
        self._client = client

    async def fetch_minute_bars(
        self,
        target: InstrumentTarget,
        trading_date: date,
        window: SessionWindow,
        now: datetime,
    ) -> MinuteBarBundle:
        seen: set[datetime] = set()
        pages: list[MinuteBarPage] = []
        request_at = min(window.closes_at, _floor_minute(now))
        for _ in range(_MAX_PAGES):
            page_rows, crossed = await self._fetch_page(target, trading_date, request_at, pages)
            kept = tuple(
                bar
                for bar in page_rows
                if bar.bar_started_at not in seen
                and window.opens_at <= bar.bar_started_at <= window.closes_at
                and bar.bar_started_at + _MINUTE <= now
            )
            seen.update(bar.bar_started_at for bar in kept)
            pages[-1] = MinuteBarPage(pages[-1].raw_response, kept)
            if not page_rows or crossed:
                break
            earliest = min(bar.bar_started_at for bar in page_rows)
            if earliest <= window.opens_at:
                break
            request_at = earliest - _MINUTE
        return MinuteBarBundle(
            target=target,
            trading_date=trading_date,
            pages=tuple(pages),
            collected_at=max(page.raw_response.received_at for page in pages),
        )

    async def close(self) -> None:
        await self._client.close()

    async def _fetch_page(
        self,
        target: InstrumentTarget,
        trading_date: date,
        request_at: datetime,
        pages: list[MinuteBarPage],
    ) -> tuple[tuple[MinuteBar, ...], bool]:
        hour = request_at.astimezone(_SEOUL).strftime("%H%M%S")
        raw = await self._client.get(
            endpoint=MINUTE_BARS_ENDPOINT,
            transaction_id=_TRANSACTION_ID,
            params={
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": target.symbol,
                "FID_INPUT_HOUR_1": hour,
                "FID_PW_DATA_INCU_YN": "Y",
            },
            request_fingerprint=f"minute_bars:{target.symbol}:{trading_date}:{hour}",
        )
        pages.append(MinuteBarPage(raw_from(BrokerOperation.MINUTE_BARS, raw), ()))
        response = parse_response(raw, KisMinuteBarsResponse, BrokerOperation.MINUTE_BARS)
        rows = tuple(minute_bar_from(target, item, raw.received_at) for item in response.output2)
        crossed = any(bar.trading_date != trading_date for bar in rows)
        return tuple(bar for bar in rows if bar.trading_date == trading_date), crossed


def _floor_minute(moment: datetime) -> datetime:
    seoul = moment.astimezone(_SEOUL)
    return seoul.replace(second=0, microsecond=0).astimezone(UTC)
