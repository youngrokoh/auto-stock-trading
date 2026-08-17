from typing import TYPE_CHECKING

from auto_stock_trading.domain.market_data.adjustment_datasets import (
    AdjustedBarRecord,
    AdjustmentDatasetRecord,
    DatasetActionRecord,
)
from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod

if TYPE_CHECKING:
    from auto_stock_trading.adapters.database.market_data_adjustment_rows import (
        AdjustedMarketBarRow,
        AdjustmentDatasetActionRow,
        AdjustmentDatasetRow,
    )


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


def adjusted_bar_record(
    row: AdjustedMarketBarRow,
    source: str,
    source_bar_version: int,
) -> AdjustedBarRecord:
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
        source=source,
        source_bar_version=source_bar_version,
    )


def dataset_action_record(row: AdjustmentDatasetActionRow, source: str) -> DatasetActionRecord:
    return DatasetActionRecord(
        dataset_id=row.dataset_id,
        corporate_action_id=row.corporate_action_id,
        action_key=row.action_key,
        action_version=row.action_version,
        event_date=row.event_date,
        event_price_factor=row.event_price_factor,
        event_volume_factor=row.event_volume_factor,
        source=source,
    )
