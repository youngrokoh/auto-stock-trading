from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AdjustedMarketDataResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class CorporateActionVersionResponse(AdjustedMarketDataResponse):
    corporate_action_id: UUID
    action_key: UUID
    version: int
    valid_from: datetime
    superseded_at: datetime | None
    action_type: str
    lifecycle: str
    quality: str
    announced_at: datetime | None
    announcement_date: date
    time_precision: str
    ex_date: date | None
    effective_date: date | None
    record_date: date | None
    payment_date: date | None
    share_multiplier: Decimal | None
    cash_amount: Decimal | None
    currency: str | None
    subscription_price: Decimal | None
    related_instrument_id: UUID | None
    source: str
    source_event_id: str
    source_reference: str
    available_at: datetime
    received_at: datetime


class CorporateActionsResponse(AdjustedMarketDataResponse):
    symbol: str
    start_date: date | None
    end_date: date | None
    knowledge_cutoff_at: datetime | None
    include_history: bool
    actions: tuple[CorporateActionVersionResponse, ...]


class AdjustedDatasetResponse(AdjustedMarketDataResponse):
    dataset_id: UUID
    symbol: str
    method: str
    interval: str
    range_start: date
    price_cutoff_date: date
    knowledge_cutoff_at: datetime
    algorithm_version: str
    input_bar_version_hash: str
    action_version_hash: str
    status: str
    generated_at: datetime
    superseded_at: datetime | None
    failure_code: str | None


class AdjustedDailyBarResponse(AdjustedMarketDataResponse):
    trading_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    trading_value: Decimal
    price_factor: Decimal
    volume_factor: Decimal
    source: str
    source_bar_id: UUID
    source_bar_version: int


class AppliedCorporateActionResponse(AdjustedMarketDataResponse):
    corporate_action_id: UUID
    action_key: UUID
    action_version: int
    event_date: date
    event_price_factor: Decimal
    event_volume_factor: Decimal
    source: str


class AdjustedDailyBarsResponse(AdjustedMarketDataResponse):
    dataset: AdjustedDatasetResponse
    bars: tuple[AdjustedDailyBarResponse, ...]
    applied_actions: tuple[AppliedCorporateActionResponse, ...]


class AdjustedDatasetsForActionResponse(AdjustedMarketDataResponse):
    action_key: UUID
    datasets: tuple[AdjustedDatasetResponse, ...]
