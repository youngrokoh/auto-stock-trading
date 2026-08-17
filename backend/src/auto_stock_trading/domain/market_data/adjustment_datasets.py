from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod


@dataclass(frozen=True, slots=True)
class AdjustmentRequest:
    symbol: str
    method: AdjustmentMethod
    range_start: date
    price_cutoff_date: date
    knowledge_cutoff_at: datetime


@dataclass(frozen=True, slots=True)
class AdjustmentDatasetRecord:
    dataset_id: UUID
    symbol: str
    method: AdjustmentMethod
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


@dataclass(frozen=True, slots=True)
class AdjustedBarRecord:
    dataset_id: UUID
    source_bar_id: UUID
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
    source_bar_version: int


@dataclass(frozen=True, slots=True)
class DatasetActionRecord:
    dataset_id: UUID
    corporate_action_id: UUID
    action_key: UUID
    action_version: int
    event_date: date
    event_price_factor: Decimal
    event_volume_factor: Decimal
    source: str
