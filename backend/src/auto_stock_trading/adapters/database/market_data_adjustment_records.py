from dataclasses import dataclass
from typing import TYPE_CHECKING

from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.adapters.database.market_data_adjustment_rows import (
        AdjustedMarketBarRow,
        AdjustmentDatasetActionRow,
        AdjustmentDatasetRow,
    )


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


@dataclass(frozen=True, slots=True)
class DatasetActionRecord:
    dataset_id: UUID
    corporate_action_id: UUID
    action_key: UUID
    action_version: int
    event_date: date
    event_price_factor: Decimal
    event_volume_factor: Decimal


def dataset_record(row: AdjustmentDatasetRow, symbol: str) -> AdjustmentDatasetRecord:
    return AdjustmentDatasetRecord(
        dataset_id=row.id,
        symbol=symbol,
        method=AdjustmentMethod(row.method),
        interval=row.interval,
        range_start=row.range_start,
        price_cutoff_date=row.price_cutoff_date,
        knowledge_cutoff_at=row.knowledge_cutoff_at,
        algorithm_version=row.algorithm_version,
        input_bar_version_hash=row.input_bar_version_hash,
        action_version_hash=row.action_version_hash,
        status=row.status,
        generated_at=row.generated_at,
        superseded_at=row.superseded_at,
        failure_code=row.failure_code,
    )


def adjusted_bar_record(row: AdjustedMarketBarRow) -> AdjustedBarRecord:
    return AdjustedBarRecord(
        dataset_id=row.dataset_id,
        source_bar_id=row.source_bar_id,
        trading_date=row.trading_date,
        open_price=row.open_price,
        high_price=row.high_price,
        low_price=row.low_price,
        close_price=row.close_price,
        volume=row.volume,
        trading_value=row.trading_value,
        price_factor=row.price_factor,
        volume_factor=row.volume_factor,
    )


def dataset_action_record(row: AdjustmentDatasetActionRow) -> DatasetActionRecord:
    return DatasetActionRecord(
        dataset_id=row.dataset_id,
        corporate_action_id=row.corporate_action_id,
        action_key=row.action_key,
        action_version=row.action_version,
        event_date=row.event_date,
        event_price_factor=row.event_price_factor,
        event_volume_factor=row.event_volume_factor,
    )
