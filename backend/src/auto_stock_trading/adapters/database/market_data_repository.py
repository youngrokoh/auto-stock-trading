from typing import TYPE_CHECKING, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_bar_repository import (
    MarketBarEvidence,
    MarketBarRange,
    confirm_market_bar,
    read_market_bars,
    save_market_bar,
)
from auto_stock_trading.adapters.database.market_data_minute_bar_repository import (
    read_minute_bars,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    QuoteRow,
    RawApiResponseRow,
    SyncStatusRow,
)
from auto_stock_trading.adapters.database.market_data_statements import (
    instrument_identifier,
    instrument_upsert,
    quote_upsert,
    success_upsert,
)
from auto_stock_trading.domain.market_data.models import (
    BrokerOperation,
    DailyBar,
    Instrument,
    InstrumentTarget,
    MarketDataBundle,
    ProductType,
    Quote,
    SyncState,
    VersionedDailyBar,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from auto_stock_trading.domain.market_data.minute_bars import VersionedMinuteBar


@final
class PostgresMarketDataRepository:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresMarketDataRepository:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresMarketDataRepository:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None:
        statement = insert(SyncStatusRow).values(
            id=uuid4(),
            source="KIS",
            operation="market_data_bundle",
            symbol=target.symbol,
            state=SyncState.RUNNING.value,
            started_at=started_at,
            completed_at=None,
            error_code=None,
            error_message=None,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_sync_target",
            set_={
                "state": SyncState.RUNNING.value,
                "started_at": started_at,
                "completed_at": None,
                "error_code": None,
                "error_message": None,
            },
        )
        async with self._sessions.begin() as session:
            _ = await session.execute(statement)

    async def save_bundle(self, bundle: MarketDataBundle) -> None:
        async with self._sessions.begin() as session:
            raw_ids: dict[BrokerOperation, UUID] = {}
            for raw in bundle.raw_responses:
                raw_id = uuid4()
                raw_ids[raw.operation] = raw_id
                session.add(
                    RawApiResponseRow(
                        id=raw_id,
                        source="KIS",
                        operation=raw.operation.value,
                        endpoint=raw.endpoint,
                        request_fingerprint=raw.request_fingerprint,
                        received_at=raw.received_at,
                        payload_json=raw.payload_json,
                    )
                )
            instrument_id = instrument_identifier(bundle)
            _ = await session.execute(instrument_upsert(bundle, instrument_id, bundle.collected_at))
            _ = await session.execute(quote_upsert(bundle, instrument_id, raw_ids))
            for bar in bundle.daily_bars:
                await save_market_bar(
                    session,
                    MarketBarEvidence(
                        bar,
                        instrument_id,
                        raw_ids[BrokerOperation.DAILY_BARS],
                    ),
                )
            _ = await session.execute(success_upsert(bundle))

    async def confirm_daily_bar(self, bar: DailyBar, confirmed_at: datetime) -> bool:
        async with self._sessions.begin() as session:
            return await confirm_market_bar(session, bar, confirmed_at)

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        statement = insert(SyncStatusRow).values(
            id=uuid4(),
            source="KIS",
            operation="market_data_bundle",
            symbol=target.symbol,
            state=SyncState.FAILED.value,
            started_at=failed_at,
            completed_at=failed_at,
            error_code=error_code,
            error_message=error_message,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_sync_target",
            set_={
                "state": SyncState.FAILED.value,
                "completed_at": failed_at,
                "error_code": error_code,
                "error_message": error_message,
            },
        )
        async with self._sessions.begin() as session:
            _ = await session.execute(statement)

    async def instruments(self) -> tuple[Instrument, ...]:
        async with self._sessions() as session:
            rows = tuple(
                (await session.scalars(select(InstrumentRow).order_by(InstrumentRow.symbol))).all()
            )
        return tuple(_instrument(row) for row in rows)

    async def instrument(self, symbol: str) -> Instrument | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(InstrumentRow)
                .where(InstrumentRow.symbol == symbol)
                .order_by(InstrumentRow.updated_at.desc())
                .limit(1)
            )
        return _instrument(row) if row is not None else None

    async def quote(self, symbol: str) -> Quote | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(QuoteRow)
                .join(InstrumentRow, QuoteRow.instrument_id == InstrumentRow.id)
                .where(InstrumentRow.symbol == symbol)
                .order_by(QuoteRow.as_of.desc())
                .limit(1)
            )
        if row is None:
            return None
        return Quote(
            symbol=symbol,
            price=row.price,
            open_price=row.open_price,
            high_price=row.high_price,
            low_price=row.low_price,
            previous_close=row.previous_close,
            change=row.change,
            change_percent=row.change_percent,
            volume=row.volume,
            trading_value=row.trading_value,
            currency=row.currency,
            source=row.source,
            as_of=row.as_of,
            received_at=row.received_at,
        )

    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[VersionedDailyBar, ...]:
        return await read_market_bars(
            self._sessions,
            MarketBarRange(symbol, start_date, end_date),
        )

    async def minute_bars(
        self,
        symbol: str,
        trading_date: date,
    ) -> tuple[VersionedMinuteBar, ...]:
        return await read_minute_bars(self._sessions, symbol, trading_date)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def _instrument(row: InstrumentRow) -> Instrument:
    return Instrument(
        country=row.country,
        exchange=row.exchange,
        symbol=row.symbol,
        product_type=ProductType(row.product_type),
        currency=row.currency,
        name=row.name,
        english_name=row.english_name,
        listed_on=row.listed_on,
        delisted_on=row.delisted_on,
        trading_status=row.trading_status,
        source=row.source,
        source_as_of=row.source_as_of,
    )
