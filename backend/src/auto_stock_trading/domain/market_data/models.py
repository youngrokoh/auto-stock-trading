from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, NewType, override
from uuid import UUID

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from auto_stock_trading.domain.market_data.listed_shares import ListedShareCount

InstrumentId = NewType("InstrumentId", UUID)


class ProductType(StrEnum):
    STOCK = "stock"
    ETF = "etf"


class SyncState(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class BarFinality(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class MarketBarInvariant(StrEnum):
    UNADJUSTED = "market_bar accepts only unadjusted observations"
    VALIDITY = "corrected market bar evidence must be newer than the current version"


@dataclass(frozen=True, slots=True)
class InvalidMarketBarError(Exception):
    invariant: MarketBarInvariant

    @override
    def __str__(self) -> str:
        return self.invariant.value


class BrokerOperation(StrEnum):
    INSTRUMENT = "instrument"
    QUOTE = "quote"
    DAILY_BARS = "daily_bars"
    MINUTE_BARS = "minute_bars"
    MARKET_CALENDAR = "market_calendar"
    INVESTOR_FLOWS = "investor_flows"
    ETF_MASTER = "etf_master"
    ETF_NAV = "etf_nav"
    STOCK_MASTER = "stock_master"
    ACCOUNT_BALANCE = "account_balance"
    ORDER_SUBMIT = "order_submit"
    ORDER_CANCEL = "order_cancel"
    ORDER_FILLS = "order_fills"


@dataclass(frozen=True, slots=True)
class InstrumentTarget:
    symbol: str
    product_type: ProductType


@dataclass(frozen=True, slots=True)
class RawBrokerResponse:
    operation: BrokerOperation
    endpoint: str
    request_fingerprint: str
    received_at: datetime
    payload_json: str


@dataclass(frozen=True, slots=True)
class Instrument:
    country: str
    exchange: str
    symbol: str
    product_type: ProductType
    currency: str
    name: str
    english_name: str | None
    listed_on: date | None
    delisted_on: date | None
    trading_status: str
    source: str
    source_as_of: date


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    price: Decimal
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    previous_close: Decimal
    change: Decimal
    change_percent: Decimal
    volume: int
    trading_value: Decimal
    currency: str
    source: str
    as_of: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DailyBar:
    symbol: str
    trading_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    trading_value: Decimal
    adjusted: bool
    correction_code: str | None
    split_ratio: Decimal | None
    source: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedDailyBar:
    bar: DailyBar
    finality: BarFinality
    confirmed_at: datetime | None
    version: int
    valid_from: datetime
    superseded_at: datetime | None


@dataclass(frozen=True, slots=True)
class QuoteObservation:
    quote: Quote
    raw: RawBrokerResponse


@dataclass(frozen=True, slots=True)
class QuoteSnapshotObservation:
    """유니버스 스윕용 관측. 같은 응답에서 상장주식수까지 함께 읽는다."""

    quote: Quote
    listed_shares: ListedShareCount
    raw: RawBrokerResponse


@dataclass(frozen=True, slots=True)
class MarketDataBundle:
    target: InstrumentTarget
    instrument: Instrument
    quote: Quote
    listed_shares: ListedShareCount
    daily_bars: tuple[DailyBar, ...]
    raw_responses: tuple[RawBrokerResponse, ...]
    collected_at: datetime
