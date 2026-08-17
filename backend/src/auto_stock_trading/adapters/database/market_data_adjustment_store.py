from typing import TYPE_CHECKING, Final, final
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_calendar_rows import MarketCalendarRow
from auto_stock_trading.adapters.database.market_data_adjustment_records import (
    AdjustedBarRecord,
    AdjustmentDatasetRecord,
    AdjustmentRequest,
    DatasetActionRecord,
    adjusted_bar_record,
    dataset_action_record,
    dataset_record,
)
from auto_stock_trading.adapters.database.market_data_adjustment_rows import (
    AdjustedMarketBarRow,
    AdjustmentDatasetActionRow,
    AdjustmentDatasetRow,
)
from auto_stock_trading.adapters.database.market_data_corporate_action_repository import (
    versioned_corporate_action,
)
from auto_stock_trading.adapters.database.market_data_corporate_action_store import (
    UnknownInstrumentError,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    CorporateActionRow,
    InstrumentRow,
    MarketBarRow,
)
from auto_stock_trading.adapters.database.market_data_sync_statements import (
    SyncTarget,
    sync_failed,
    sync_succeeded,
)
from auto_stock_trading.domain.market_data.adjustments import (
    ADJUSTMENT_ALGORITHM_VERSION,
    AdjustmentError,
    AdjustmentFailure,
    AdjustmentInputs,
    AdjustmentMethod,
    AdjustmentPlan,
    InputBar,
    action_version_hash,
    build_adjustment_plan,
    input_bar_version_hash,
)
from auto_stock_trading.domain.market_data.models import BarFinality

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.domain.market_data.corporate_actions import VersionedCorporateAction

_INTERVAL: Final = "1d"
_SYNC_SOURCE: Final = "INTERNAL"
_SYNC_OPERATION: Final = "adjusted_prices"
_OPEN_STATUSES: Final = ("open", "shortened")


@final
class PostgresAdjustmentStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresAdjustmentStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresAdjustmentStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def build_dataset(
        self,
        request: AdjustmentRequest,
        generated_at: datetime,
    ) -> AdjustmentDatasetRecord:
        async with self._sessions() as session:
            instrument = await session.scalar(
                select(InstrumentRow).where(InstrumentRow.symbol == request.symbol).limit(1)
            )
            if instrument is None:
                raise UnknownInstrumentError(request.symbol)
            open_dates = await self._open_dates(session, instrument, request)
            bars = await self._input_bars(session, instrument.id, request)
            actions = await self._actions_as_of(session, instrument.id, request)
        try:
            plan = build_adjustment_plan(
                AdjustmentInputs(
                    method=request.method,
                    range_start=request.range_start,
                    price_cutoff_date=request.price_cutoff_date,
                    bars=bars,
                    actions=actions,
                    open_dates=open_dates,
                    listed_on=instrument.listed_on,
                    delisted_on=instrument.delisted_on,
                )
            )
        except AdjustmentError as error:
            await self._record_failure(request, instrument.id, generated_at, error, bars)
            raise
        return await self._publish(request, instrument.id, generated_at, plan)

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
            select(AdjustedMarketBarRow)
            .where(AdjustedMarketBarRow.dataset_id == dataset_id)
            .order_by(AdjustedMarketBarRow.trading_date)
        )
        async with self._sessions() as session:
            rows = tuple((await session.scalars(statement)).all())
        return tuple(adjusted_bar_record(row) for row in rows)

    async def read_dataset_actions(self, dataset_id: UUID) -> tuple[DatasetActionRecord, ...]:
        statement = (
            select(AdjustmentDatasetActionRow)
            .where(AdjustmentDatasetActionRow.dataset_id == dataset_id)
            .order_by(AdjustmentDatasetActionRow.event_date, AdjustmentDatasetActionRow.action_key)
        )
        async with self._sessions() as session:
            rows = tuple((await session.scalars(statement)).all())
        return tuple(dataset_action_record(row) for row in rows)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    def _dataset_statement(self, symbol: str) -> Select[tuple[AdjustmentDatasetRow, str]]:
        return (
            select(AdjustmentDatasetRow, InstrumentRow.symbol)
            .join(InstrumentRow, AdjustmentDatasetRow.instrument_id == InstrumentRow.id)
            .where(InstrumentRow.symbol == symbol)
        )

    async def _open_dates(
        self,
        session: AsyncSession,
        instrument: InstrumentRow,
        request: AdjustmentRequest,
    ) -> tuple[date, ...]:
        statement = select(
            MarketCalendarRow.trading_date,
            MarketCalendarRow.session_status,
        ).where(
            MarketCalendarRow.country == instrument.country,
            MarketCalendarRow.exchange == instrument.exchange,
            MarketCalendarRow.session_type == "regular",
            MarketCalendarRow.superseded_at.is_(None),
            MarketCalendarRow.trading_date >= request.range_start,
            MarketCalendarRow.trading_date <= request.price_cutoff_date,
        )
        rows = (await session.execute(statement)).tuples().all()
        expected_days = (request.price_cutoff_date - request.range_start).days + 1
        if len({row[0] for row in rows}) != expected_days:
            raise AdjustmentError(AdjustmentFailure.CALENDAR_COVERAGE)
        return tuple(sorted(row[0] for row in rows if row[1] in _OPEN_STATUSES))

    async def _input_bars(
        self,
        session: AsyncSession,
        instrument_id: UUID,
        request: AdjustmentRequest,
    ) -> tuple[InputBar, ...]:
        statement = (
            select(MarketBarRow)
            .where(
                MarketBarRow.instrument_id == instrument_id,
                MarketBarRow.interval == _INTERVAL,
                MarketBarRow.superseded_at.is_(None),
                MarketBarRow.trading_date >= request.range_start,
                MarketBarRow.trading_date <= request.price_cutoff_date,
            )
            .order_by(MarketBarRow.trading_date)
        )
        rows = tuple((await session.scalars(statement)).all())
        return tuple(
            InputBar(
                bar_id=row.id,
                version=row.version,
                trading_date=row.trading_date,
                open_price=row.open_price,
                high_price=row.high_price,
                low_price=row.low_price,
                close_price=row.close_price,
                volume=row.volume,
                trading_value=row.trading_value,
                finality=BarFinality(row.finality),
            )
            for row in rows
        )

    async def _actions_as_of(
        self,
        session: AsyncSession,
        instrument_id: UUID,
        request: AdjustmentRequest,
    ) -> tuple[VersionedCorporateAction, ...]:
        known = (
            select(
                CorporateActionRow.action_key.label("action_key"),
                func.max(CorporateActionRow.version).label("version"),
            )
            .where(
                CorporateActionRow.instrument_id == instrument_id,
                CorporateActionRow.available_at <= request.knowledge_cutoff_at,
            )
            .group_by(CorporateActionRow.action_key)
            .subquery()
        )
        statement = select(CorporateActionRow).join(
            known,
            (CorporateActionRow.action_key == known.c.action_key)
            & (CorporateActionRow.version == known.c.version),
        )
        rows = tuple((await session.scalars(statement)).all())
        return tuple(versioned_corporate_action(row) for row in rows)

    async def _record_failure(
        self,
        request: AdjustmentRequest,
        instrument_id: UUID,
        generated_at: datetime,
        error: AdjustmentError,
        bars: tuple[InputBar, ...],
    ) -> None:
        async with self._sessions.begin() as session:
            session.add(
                AdjustmentDatasetRow(
                    id=uuid4(),
                    instrument_id=instrument_id,
                    interval=_INTERVAL,
                    method=request.method.value,
                    range_start=request.range_start,
                    price_cutoff_date=request.price_cutoff_date,
                    knowledge_cutoff_at=request.knowledge_cutoff_at,
                    algorithm_version=ADJUSTMENT_ALGORITHM_VERSION,
                    input_bar_version_hash=input_bar_version_hash(bars),
                    action_version_hash=action_version_hash(()),
                    status="failed",
                    generated_at=generated_at,
                    superseded_at=None,
                    failure_code=error.failure.value,
                )
            )
            _ = await session.execute(
                sync_failed(
                    SyncTarget(_SYNC_SOURCE, _SYNC_OPERATION, request.symbol),
                    generated_at,
                    error.failure.value,
                    str(error)[:500],
                )
            )

    async def _publish(
        self,
        request: AdjustmentRequest,
        instrument_id: UUID,
        generated_at: datetime,
        plan: AdjustmentPlan,
    ) -> AdjustmentDatasetRecord:
        async with self._sessions.begin() as session:
            existing = await session.scalar(
                self._request_scope(request, instrument_id).where(
                    AdjustmentDatasetRow.status == "published",
                    AdjustmentDatasetRow.input_bar_version_hash == plan.input_bar_version_hash,
                    AdjustmentDatasetRow.action_version_hash == plan.action_version_hash,
                )
            )
            if existing is not None:
                return dataset_record(existing, request.symbol)
            _ = await session.execute(
                update(AdjustmentDatasetRow)
                .where(
                    AdjustmentDatasetRow.instrument_id == instrument_id,
                    AdjustmentDatasetRow.interval == _INTERVAL,
                    AdjustmentDatasetRow.method == request.method.value,
                    AdjustmentDatasetRow.range_start == request.range_start,
                    AdjustmentDatasetRow.price_cutoff_date == request.price_cutoff_date,
                    AdjustmentDatasetRow.knowledge_cutoff_at == request.knowledge_cutoff_at,
                    AdjustmentDatasetRow.algorithm_version == ADJUSTMENT_ALGORITHM_VERSION,
                    AdjustmentDatasetRow.status == "published",
                )
                .values(status="superseded", superseded_at=generated_at)
            )
            dataset = AdjustmentDatasetRow(
                id=uuid4(),
                instrument_id=instrument_id,
                interval=_INTERVAL,
                method=request.method.value,
                range_start=request.range_start,
                price_cutoff_date=request.price_cutoff_date,
                knowledge_cutoff_at=request.knowledge_cutoff_at,
                algorithm_version=ADJUSTMENT_ALGORITHM_VERSION,
                input_bar_version_hash=plan.input_bar_version_hash,
                action_version_hash=plan.action_version_hash,
                status="building",
                generated_at=generated_at,
                superseded_at=None,
                failure_code=None,
            )
            session.add(dataset)
            await session.flush()
            for applied in plan.applied_actions:
                session.add(
                    AdjustmentDatasetActionRow(
                        dataset_id=dataset.id,
                        corporate_action_id=applied.action.corporate_action_id,
                        action_key=applied.action.action_key,
                        action_version=applied.action.version,
                        event_date=applied.event_date,
                        event_price_factor=applied.price_factor,
                        event_volume_factor=applied.volume_factor,
                    )
                )
            for adjusted in plan.adjusted_bars:
                session.add(
                    AdjustedMarketBarRow(
                        id=uuid4(),
                        dataset_id=dataset.id,
                        source_bar_id=adjusted.source.bar_id,
                        trading_date=adjusted.source.trading_date,
                        open_price=adjusted.open_price,
                        high_price=adjusted.high_price,
                        low_price=adjusted.low_price,
                        close_price=adjusted.close_price,
                        volume=adjusted.volume,
                        trading_value=adjusted.trading_value,
                        price_factor=adjusted.price_factor,
                        volume_factor=adjusted.volume_factor,
                    )
                )
            dataset.status = "published"
            _ = await session.execute(
                sync_succeeded(
                    SyncTarget(_SYNC_SOURCE, _SYNC_OPERATION, request.symbol),
                    generated_at,
                )
            )
            return dataset_record(dataset, request.symbol)

    def _request_scope(
        self,
        request: AdjustmentRequest,
        instrument_id: UUID,
    ) -> Select[tuple[AdjustmentDatasetRow]]:
        return select(AdjustmentDatasetRow).where(
            AdjustmentDatasetRow.instrument_id == instrument_id,
            AdjustmentDatasetRow.interval == _INTERVAL,
            AdjustmentDatasetRow.method == request.method.value,
            AdjustmentDatasetRow.range_start == request.range_start,
            AdjustmentDatasetRow.price_cutoff_date == request.price_cutoff_date,
            AdjustmentDatasetRow.knowledge_cutoff_at == request.knowledge_cutoff_at,
            AdjustmentDatasetRow.algorithm_version == ADJUSTMENT_ALGORITHM_VERSION,
        )
