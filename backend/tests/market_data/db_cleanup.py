from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from auto_stock_trading.adapters.database.market_data_adjustment_rows import (
    AdjustmentDatasetRow,
)
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


async def purge_instruments(
    executor: AsyncConnection | AsyncSession,
    symbols: tuple[str, ...],
) -> None:
    instrument_ids = (
        select(InstrumentRow.id).where(InstrumentRow.symbol.in_(symbols)).scalar_subquery()
    )
    _ = await executor.execute(
        delete(AdjustmentDatasetRow).where(AdjustmentDatasetRow.instrument_id.in_(instrument_ids))
    )
    _ = await executor.execute(delete(InstrumentRow).where(InstrumentRow.symbol.in_(symbols)))
