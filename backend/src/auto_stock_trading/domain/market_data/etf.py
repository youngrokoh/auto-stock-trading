from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from auto_stock_trading.domain.market_data.models import RawBrokerResponse


@dataclass(frozen=True, slots=True)
class EtfProfile:
    symbol: str
    isin: str
    name: str
    source: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedEtfProfile:
    symbol: str
    isin: str
    name: str
    source: str
    received_at: datetime
    version: int
    valid_from: datetime
    superseded_at: datetime | None


@dataclass(frozen=True, slots=True)
class EtfMasterBundle:
    profiles: tuple[EtfProfile, ...]
    raw: RawBrokerResponse
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class EtfNavSnapshot:
    symbol: str
    price: Decimal
    change_percent: Decimal
    volume: int
    previous_volume: int
    nav: Decimal
    divergence_rate: Decimal
    tracking_error: Decimal
    tracking_multiple: Decimal
    net_asset_total: int
    listed_shares: int
    manager: str
    index_name: str
    listing_date: date | None
    currency: str
    source: str
    as_of: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class EtfNavObservation:
    snapshot: EtfNavSnapshot
    raw: RawBrokerResponse


@dataclass(frozen=True, slots=True)
class EtfListing:
    profile: VersionedEtfProfile
    snapshot: EtfNavSnapshot | None
