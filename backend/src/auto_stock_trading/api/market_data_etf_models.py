from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class EtfResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class EtfSnapshotResponse(EtfResponse):
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
    as_of: datetime
    received_at: datetime


class EtfListingResponse(EtfResponse):
    symbol: str
    isin: str
    name: str
    snapshot: EtfSnapshotResponse | None


class EtfsResponse(EtfResponse):
    source: str = "KIS"
    master_source: str = "KIS_MASTER"
    net_asset_unit: str = "hundred_million_krw"
    etfs: tuple[EtfListingResponse, ...]


class DistributionYieldResponse(EtfResponse):
    value: Decimal | None
    unavailable_reason: str | None
    formula: str
    distribution_total: Decimal | None
    distribution_count: int
    window_start: date | None
    window_end: date | None


class EtfDetailResponse(EtfResponse):
    symbol: str
    isin: str
    name: str
    source: str = "KIS"
    master_source: str = "KIS_MASTER"
    net_asset_unit: str = "hundred_million_krw"
    snapshot: EtfSnapshotResponse | None
    distribution_yield: DistributionYieldResponse
