from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class MarketDataResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class InstrumentResponse(MarketDataResponse):
    country: str
    exchange: str
    symbol: str
    product_type: str
    currency: str
    name: str
    english_name: str | None
    listed_on: date | None
    delisted_on: date | None
    trading_status: str
    source: str
    source_as_of: date


class InstrumentsResponse(MarketDataResponse):
    instruments: tuple[InstrumentResponse, ...]


class QuoteResponse(MarketDataResponse):
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


class DailyBarResponse(MarketDataResponse):
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
    finality: str
    confirmed_at: datetime | None
    version: int
    valid_from: datetime


class DailyBarsResponse(MarketDataResponse):
    symbol: str
    interval: str = "1d"
    start_date: date | None
    end_date: date | None
    source: str | None
    bars: tuple[DailyBarResponse, ...]


class MinuteBarResponse(MarketDataResponse):
    bar_started_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    cumulative_trading_value: Decimal
    source: str
    received_at: datetime
    finality: str
    confirmed_at: datetime | None
    version: int
    valid_from: datetime


class MinuteBarsResponse(MarketDataResponse):
    symbol: str
    interval: str = "1m"
    trading_date: date
    source: str | None
    bars: tuple[MinuteBarResponse, ...]
