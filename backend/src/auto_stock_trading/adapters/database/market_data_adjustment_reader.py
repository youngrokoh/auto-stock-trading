from typing import TYPE_CHECKING, final

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_adjustment_records import (
    adjusted_bar_record,
    dataset_action_record,
    dataset_record,
)
from auto_stock_trading.adapters.database.market_data_adjustment_rows import (
    AdjustedMarketBarRow,
    AdjustmentDatasetActionRow,
    AdjustmentDatasetRow,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    CorporateActionRow,
    InstrumentRow,
    MarketBarRow,
)

if TYPE_CHECKING:
    from uuid import UUID

    from auto_stock_trading.domain.market_data.adjustment_datasets import (
        AdjustedBarRecord,
        AdjustmentDatasetRecord,
        DatasetActionRecord,
    )
    from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod


@final
class PostgresAdjustedPriceReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresAdjustedPriceReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresAdjustedPriceReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def read_dataset(self, dataset_id: UUID) -> AdjustmentDatasetRecord | None:
        statement = (
            select(AdjustmentDatasetRow, InstrumentRow.symbol)
            .join(InstrumentRow, AdjustmentDatasetRow.instrument_id == InstrumentRow.id)
            .where(AdjustmentDatasetRow.id == dataset_id)
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).tuples().first()
        return dataset_record(row[0], row[1]) if row is not None else None

    async def read_latest_published(
        self,
        symbol: str,
        method: AdjustmentMethod,
    ) -> AdjustmentDatasetRecord | None:
        statement = (
            self._dataset_statement(symbol)
            .where(
                AdjustmentDatasetRow.method == method.value,
                AdjustmentDatasetRow.status == "published",
            )
            .order_by(
                AdjustmentDatasetRow.price_cutoff_date.desc(),
                AdjustmentDatasetRow.generated_at.desc(),
            )
            .limit(1)
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).tuples().first()
        return dataset_record(row[0], row[1]) if row is not None else None

    async def read_datasets_for_symbol(self, symbol: str) -> tuple[AdjustmentDatasetRecord, ...]:
        statement = self._dataset_statement(symbol).order_by(AdjustmentDatasetRow.generated_at)
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(dataset_record(row[0], row[1]) for row in rows)

    async def read_datasets_for_action(
        self,
        action_key: UUID,
    ) -> tuple[AdjustmentDatasetRecord, ...]:
        statement = (
            select(AdjustmentDatasetRow, InstrumentRow.symbol)
            .join(
                AdjustmentDatasetActionRow,
                AdjustmentDatasetActionRow.dataset_id == AdjustmentDatasetRow.id,
            )
            .join(InstrumentRow, AdjustmentDatasetRow.instrument_id == InstrumentRow.id)
            .where(AdjustmentDatasetActionRow.action_key == action_key)
            .order_by(AdjustmentDatasetRow.generated_at)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(dataset_record(row[0], row[1]) for row in rows)

    async def read_adjusted_bars(self, dataset_id: UUID) -> tuple[AdjustedBarRecord, ...]:
        statement = (
            select(AdjustedMarketBarRow, MarketBarRow.source, MarketBarRow.version)
            .join(MarketBarRow, AdjustedMarketBarRow.source_bar_id == MarketBarRow.id)
            .where(AdjustedMarketBarRow.dataset_id == dataset_id)
            .order_by(AdjustedMarketBarRow.trading_date)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(adjusted_bar_record(row[0], row[1], row[2]) for row in rows)

    async def read_dataset_actions(self, dataset_id: UUID) -> tuple[DatasetActionRecord, ...]:
        statement = (
            select(AdjustmentDatasetActionRow, CorporateActionRow.source)
            .join(
                CorporateActionRow,
                AdjustmentDatasetActionRow.corporate_action_id == CorporateActionRow.id,
            )
            .where(AdjustmentDatasetActionRow.dataset_id == dataset_id)
            .order_by(AdjustmentDatasetActionRow.event_date, AdjustmentDatasetActionRow.action_key)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(dataset_action_record(row[0], row[1]) for row in rows)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    def _dataset_statement(self, symbol: str) -> Select[tuple[AdjustmentDatasetRow, str]]:
        return (
            select(AdjustmentDatasetRow, InstrumentRow.symbol)
            .join(InstrumentRow, AdjustmentDatasetRow.instrument_id == InstrumentRow.id)
            .where(InstrumentRow.symbol == symbol)
        )
