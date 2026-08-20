"""종목 유니버스 사실 타입. 업종 키는 KOSPI200 섹터업종 코드다(종목 유니버스 계약)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.market_data.models import RawBrokerResponse


@dataclass(frozen=True, slots=True)
class StockProfile:
    symbol: str
    isin: str
    name: str
    sector_code: str
    source: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedStockProfile:
    symbol: str
    isin: str
    name: str
    sector_code: str
    source: str
    received_at: datetime
    version: int
    valid_from: datetime
    superseded_at: datetime | None


@dataclass(frozen=True, slots=True)
class StockMasterBundle:
    profiles: tuple[StockProfile, ...]
    raw: RawBrokerResponse
    collected_at: datetime
