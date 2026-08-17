from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from auto_stock_trading.domain.market_data.models import (
        BarFinality,
        InstrumentTarget,
        RawBrokerResponse,
    )


class MinuteBarInvariant(StrEnum):
    VALIDITY = "corrected minute bar evidence must be newer than the current version"


@dataclass(frozen=True, slots=True)
class InvalidMinuteBarError(Exception):
    invariant: MinuteBarInvariant

    @override
    def __str__(self) -> str:
        return self.invariant.value


@dataclass(frozen=True, slots=True)
class MinuteBar:
    symbol: str
    trading_date: date
    bar_started_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    cumulative_trading_value: Decimal
    source: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedMinuteBar:
    bar: MinuteBar
    finality: BarFinality
    confirmed_at: datetime | None
    version: int
    valid_from: datetime
    superseded_at: datetime | None


@dataclass(frozen=True, slots=True)
class MinuteBarPage:
    raw_response: RawBrokerResponse
    bars: tuple[MinuteBar, ...]


@dataclass(frozen=True, slots=True)
class MinuteBarBundle:
    target: InstrumentTarget
    trading_date: date
    pages: tuple[MinuteBarPage, ...]
    collected_at: datetime

    @property
    def bars(self) -> tuple[MinuteBar, ...]:
        merged = [bar for page in self.pages for bar in page.bars]
        return tuple(sorted(merged, key=lambda bar: bar.bar_started_at))
