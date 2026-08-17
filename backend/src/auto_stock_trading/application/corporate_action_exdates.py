from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    ClosedMarketSession,
    MarketSessionType,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.domain.market_data.calendar import MarketCalendarRecord
    from auto_stock_trading.domain.market_data.corporate_actions import VersionedCorporateAction

EX_DATE_RULE_VERSION: Final = "krx-t2-settlement-v1"


class TradingCalendar(Protocol):
    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None: ...

    async def previous_open_date(self, key: CalendarSessionKey) -> date | None: ...

    async def close(self) -> None: ...


class ExDateStore(Protocol):
    async def actions_missing_ex_date(
        self,
        symbol: str,
    ) -> tuple[VersionedCorporateAction, ...]: ...

    async def confirm_ex_date(
        self,
        item: VersionedCorporateAction,
        ex_date: date,
        confirmed_at: datetime,
    ) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ExDateResolution:
    resolved: int
    skipped: int


@dataclass(frozen=True, slots=True)
class ExDateResolver:
    calendar: TradingCalendar
    store: ExDateStore
    country: str = "KR"
    exchange: str = "XKRX"

    async def resolve(self, symbol: str, resolved_at: datetime) -> ExDateResolution:
        resolved = 0
        skipped = 0
        for item in await self.store.actions_missing_ex_date(symbol):
            record_date = item.action.record_date
            if record_date is None:
                skipped += 1
                continue
            ex_date = await self._derived_ex_date(record_date)
            if ex_date is None:
                skipped += 1
                continue
            await self.store.confirm_ex_date(item, ex_date, resolved_at)
            resolved += 1
        return ExDateResolution(resolved=resolved, skipped=skipped)

    async def _derived_ex_date(self, record_date: date) -> date | None:
        record_key = self._key(record_date)
        record_session = await self.calendar.session(record_key)
        if record_session is None:
            return None
        if isinstance(record_session.session, ClosedMarketSession):
            settlement_date = await self.calendar.previous_open_date(record_key)
        else:
            settlement_date = record_date
        if settlement_date is None:
            return None
        return await self.calendar.previous_open_date(self._key(settlement_date))

    def _key(self, trading_date: date) -> CalendarSessionKey:
        return CalendarSessionKey(
            self.country,
            self.exchange,
            trading_date,
            MarketSessionType.REGULAR,
        )
