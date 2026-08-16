from dataclasses import dataclass
from typing import Protocol, final

from auto_stock_trading.adapters.exchanges.krx_trading_hours_contracts import (
    KrxNoticeContractError,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarSessionRange,
    calendar_session_key,
)


class CalendarSourcePort(Protocol):
    async def fetch_sessions(
        self,
        query: CalendarSessionRange,
    ) -> tuple[CalendarObservation, ...]: ...

    async def close(self) -> None: ...


class NoticeSourcePort(Protocol):
    async def fetch_overrides(
        self,
        query: CalendarSessionRange,
    ) -> tuple[CalendarObservation, ...]: ...

    async def close(self) -> None: ...


@final
@dataclass(frozen=True, slots=True)
class KrxCompositeCalendarSource:
    base: CalendarSourcePort
    notices: NoticeSourcePort

    async def fetch_sessions(
        self,
        query: CalendarSessionRange,
    ) -> tuple[CalendarObservation, ...]:
        base_observations = await self.base.fetch_sessions(query)
        overrides = await self.notices.fetch_overrides(query)
        positions = {
            calendar_session_key(item.session): index
            for index, item in enumerate(base_observations)
        }
        merged = list(base_observations)
        for override in overrides:
            key = calendar_session_key(override.session)
            position = positions.get(key)
            if position is None:
                message = f"KRX notice override has no annual session for {key.trading_date}"
                raise KrxNoticeContractError(message)
            merged[position] = override
        return tuple(merged)

    async def close(self) -> None:
        try:
            await self.base.close()
        finally:
            await self.notices.close()
