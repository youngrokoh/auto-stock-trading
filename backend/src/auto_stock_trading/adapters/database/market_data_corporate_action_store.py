from dataclasses import dataclass
from typing import TYPE_CHECKING, final, override
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_corporate_action_repository import (
    CorporateActionEvidence,
    save_corporate_action,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    CorporateActionRow,
    InstrumentRow,
    RawApiResponseRow,
    SyncStatusRow,
)
from auto_stock_trading.domain.market_data.models import SyncState

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.market_data.corporate_actions import (
        CorporateAction,
        CorporateActionBundle,
        CorporateActionRawResponse,
    )

_OPERATION = "corporate_actions"


@final
@dataclass(frozen=True, slots=True)
class UnknownInstrumentError(Exception):
    symbol: str

    @override
    def __str__(self) -> str:
        return f"instrument is not registered for corporate actions: {self.symbol}"


@final
class PostgresCorporateActionStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresCorporateActionStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresCorporateActionStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def save_bundle(self, bundle: CorporateActionBundle) -> None:
        async with self._sessions.begin() as session:
            instrument_id = await session.scalar(
                select(InstrumentRow.id).where(InstrumentRow.symbol == bundle.symbol).limit(1)
            )
            if instrument_id is None:
                raise UnknownInstrumentError(bundle.symbol)
            raw_ids: dict[int, UUID] = {}
            for raw in bundle.supporting_raw_responses:
                _ = _shared_raw_id(session, raw_ids, bundle.source, raw)
            for observation in bundle.observations:
                raw_id = _shared_raw_id(session, raw_ids, bundle.source, observation.raw_response)
                action_key = await _resolve_action_key(session, instrument_id, observation.action)
                await save_corporate_action(
                    session,
                    CorporateActionEvidence(
                        action=observation.action,
                        action_key=action_key,
                        instrument_id=instrument_id,
                        raw_response_id=raw_id,
                    ),
                )

    async def mark_sync_started(self, source: str, symbol: str, started_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(_sync_started(source, symbol, started_at))

    async def mark_sync_succeeded(
        self,
        source: str,
        symbol: str,
        completed_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(_sync_succeeded(source, symbol, completed_at))

    async def mark_sync_failed(
        self,
        source: str,
        symbol: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                _sync_failed(source, symbol, failed_at, error_code, error_message)
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


async def _resolve_action_key(
    session: AsyncSession,
    instrument_id: UUID,
    action: CorporateAction,
) -> UUID:
    if action.record_date is None:
        return uuid4()
    current_key = await session.scalar(
        select(CorporateActionRow.action_key).where(
            CorporateActionRow.instrument_id == instrument_id,
            CorporateActionRow.action_type == action.action_type.value,
            CorporateActionRow.record_date == action.record_date,
            CorporateActionRow.superseded_at.is_(None),
        )
    )
    return current_key if current_key is not None else uuid4()


def _shared_raw_id(
    session: AsyncSession,
    raw_ids: dict[int, UUID],
    source: str,
    raw: CorporateActionRawResponse,
) -> UUID:
    known = raw_ids.get(id(raw))
    if known is not None:
        return known
    raw_id = uuid4()
    raw_ids[id(raw)] = raw_id
    session.add(
        RawApiResponseRow(
            id=raw_id,
            source=source,
            operation=_OPERATION,
            endpoint=raw.endpoint,
            request_fingerprint=raw.request_fingerprint,
            received_at=raw.received_at,
            payload_json=raw.payload_json,
        )
    )
    return raw_id


def _sync_started(source: str, symbol: str, started_at: datetime) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=source,
        operation=_OPERATION,
        symbol=symbol,
        state=SyncState.RUNNING.value,
        started_at=started_at,
        completed_at=None,
        last_success_at=None,
        error_code=None,
        error_message=None,
    )
    return statement.on_conflict_do_update(
        constraint="uq_sync_target",
        set_={
            "state": SyncState.RUNNING.value,
            "started_at": started_at,
            "completed_at": None,
            "error_code": None,
            "error_message": None,
        },
    )


def _sync_succeeded(source: str, symbol: str, completed_at: datetime) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=source,
        operation=_OPERATION,
        symbol=symbol,
        state=SyncState.SUCCESS.value,
        started_at=completed_at,
        completed_at=completed_at,
        last_success_at=completed_at,
        error_code=None,
        error_message=None,
    )
    return statement.on_conflict_do_update(
        constraint="uq_sync_target",
        set_={
            "state": SyncState.SUCCESS.value,
            "completed_at": completed_at,
            "last_success_at": completed_at,
            "error_code": None,
            "error_message": None,
        },
    )


def _sync_failed(
    source: str,
    symbol: str,
    failed_at: datetime,
    error_code: str,
    error_message: str,
) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=source,
        operation=_OPERATION,
        symbol=symbol,
        state=SyncState.FAILED.value,
        started_at=failed_at,
        completed_at=failed_at,
        last_success_at=None,
        error_code=error_code,
        error_message=error_message,
    )
    return statement.on_conflict_do_update(
        constraint="uq_sync_target",
        set_={
            "state": SyncState.FAILED.value,
            "completed_at": failed_at,
            "error_code": error_code,
            "error_message": error_message,
        },
    )
