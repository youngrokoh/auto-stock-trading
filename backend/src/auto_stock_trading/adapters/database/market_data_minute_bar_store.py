from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_corporate_action_store import (
    UnknownInstrumentError,
)
from auto_stock_trading.adapters.database.market_data_minute_bar_repository import (
    MinuteBarEvidence,
    confirm_minute_bar,
    read_minute_bars,
    save_minute_bar,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.adapters.database.market_data_sync_statements import (
    SyncTarget,
    sync_failed,
    sync_started,
    sync_succeeded,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from auto_stock_trading.domain.market_data.minute_bars import (
        MinuteBar,
        MinuteBarBundle,
        VersionedMinuteBar,
    )
    from auto_stock_trading.domain.market_data.models import (
        InstrumentTarget,
        RawBrokerResponse,
    )

_SOURCE: Final = "KIS"
_OPERATION: Final = "minute_bars"


@final
class PostgresMinuteBarStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresMinuteBarStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresMinuteBarStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_started(SyncTarget(_SOURCE, _OPERATION, target.symbol), started_at)
            )

    async def save_minute_bundle(self, bundle: MinuteBarBundle) -> None:
        async with self._sessions.begin() as session:
            instrument_id = await session.scalar(
                select(InstrumentRow.id)
                .where(InstrumentRow.symbol == bundle.target.symbol)
                .limit(1)
            )
            if instrument_id is None:
                raise UnknownInstrumentError(bundle.target.symbol)
            for page in bundle.pages:
                raw_id = self._add_raw_row(session, page.raw_response)
                for bar in page.bars:
                    await save_minute_bar(session, MinuteBarEvidence(bar, instrument_id, raw_id))
            _ = await session.execute(
                sync_succeeded(
                    SyncTarget(_SOURCE, _OPERATION, bundle.target.symbol),
                    bundle.collected_at,
                )
            )

    async def confirm_minute_bar(self, bar: MinuteBar, confirmed_at: datetime) -> bool:
        async with self._sessions.begin() as session:
            return await confirm_minute_bar(session, bar, confirmed_at)

    async def minute_bars(
        self,
        symbol: str,
        trading_date: date,
    ) -> tuple[VersionedMinuteBar, ...]:
        return await read_minute_bars(self._sessions, symbol, trading_date)

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_failed(
                    SyncTarget(_SOURCE, _OPERATION, target.symbol),
                    failed_at,
                    error_code,
                    error_message,
                )
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    @staticmethod
    def _add_raw_row(session: AsyncSession, raw: RawBrokerResponse) -> UUID:
        raw_id = uuid4()
        session.add(
            RawApiResponseRow(
                id=raw_id,
                source=_SOURCE,
                operation=_OPERATION,
                endpoint=raw.endpoint,
                request_fingerprint=raw.request_fingerprint,
                received_at=raw.received_at,
                payload_json=raw.payload_json,
            )
        )
        return raw_id
