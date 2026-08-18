from typing import TYPE_CHECKING, Final, final
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

from auto_stock_trading.adapters.database.market_data_rows import (
    EtfNavRow,
    EtfProfileRow,
    RawApiResponseRow,
)
from auto_stock_trading.adapters.database.market_data_sync_statements import (
    SyncTarget,
    sync_failed,
    sync_started,
    sync_succeeded,
)
from auto_stock_trading.domain.market_data.etf import VersionedEtfProfile

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from auto_stock_trading.domain.market_data.etf import (
        EtfMasterBundle,
        EtfNavObservation,
        EtfProfile,
    )
    from auto_stock_trading.domain.market_data.models import RawBrokerResponse

_SOURCE: Final = "KIS"


@final
class PostgresEtfStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresEtfStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresEtfStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def mark_started(self, operation: str, key: str, started_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(sync_started(SyncTarget(_SOURCE, operation, key), started_at))

    async def mark_succeeded(self, operation: str, key: str, completed_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_succeeded(SyncTarget(_SOURCE, operation, key), completed_at)
            )

    async def mark_failed(
        self,
        operation: str,
        key: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_failed(
                    SyncTarget(_SOURCE, operation, key),
                    failed_at,
                    error_code,
                    error_message,
                )
            )

    async def save_master_bundle(self, bundle: EtfMasterBundle) -> int:
        async with self._sessions.begin() as session:
            raw_id = self._add_raw_row(session, "etf_master", bundle.raw)
            saved = 0
            for profile in bundle.profiles:
                if await _save_profile(session, profile, raw_id):
                    saved += 1
            return saved

    async def save_nav_observation(self, observation: EtfNavObservation) -> None:
        async with self._sessions.begin() as session:
            raw_id = self._add_raw_row(session, "etf_nav", observation.raw)
            snapshot = observation.snapshot
            values = {
                "symbol": snapshot.symbol,
                "price": snapshot.price,
                "change_percent": snapshot.change_percent,
                "volume": snapshot.volume,
                "previous_volume": snapshot.previous_volume,
                "nav": snapshot.nav,
                "divergence_rate": snapshot.divergence_rate,
                "tracking_error": snapshot.tracking_error,
                "tracking_multiple": snapshot.tracking_multiple,
                "net_asset_total": snapshot.net_asset_total,
                "listed_shares": snapshot.listed_shares,
                "manager": snapshot.manager,
                "index_name": snapshot.index_name,
                "listing_date": snapshot.listing_date,
                "currency": snapshot.currency,
                "source": snapshot.source,
                "as_of": snapshot.as_of,
                "received_at": snapshot.received_at,
                "raw_response_id": raw_id,
            }
            statement = insert(EtfNavRow).values(id=uuid4(), **values)
            statement = statement.on_conflict_do_update(
                constraint="uq_etf_nav_latest_source",
                set_={key: value for key, value in values.items() if key != "symbol"},
            )
            _ = await session.execute(statement)

    async def profiles(self) -> tuple[VersionedEtfProfile, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(EtfProfileRow)
                    .where(EtfProfileRow.superseded_at.is_(None))
                    .order_by(EtfProfileRow.symbol)
                )
            ).all()
        return tuple(_versioned_profile(row) for row in rows)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    @staticmethod
    def _add_raw_row(session: AsyncSession, operation: str, raw: RawBrokerResponse) -> UUID:
        raw_id = uuid4()
        session.add(
            RawApiResponseRow(
                id=raw_id,
                source=_SOURCE,
                operation=operation,
                endpoint=raw.endpoint,
                request_fingerprint=raw.request_fingerprint,
                received_at=raw.received_at,
                payload_json=raw.payload_json,
            )
        )
        return raw_id


async def _save_profile(session: AsyncSession, profile: EtfProfile, raw_id: UUID) -> bool:
    current = await session.scalar(
        select(EtfProfileRow)
        .where(
            EtfProfileRow.symbol == profile.symbol,
            EtfProfileRow.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current is not None and current.isin == profile.isin and current.name == profile.name:
        if profile.received_at > current.received_at:
            current.received_at = profile.received_at
            current.raw_response_id = raw_id
        return False
    version = 1
    if current is not None:
        if profile.received_at <= current.received_at:
            return False
        current.superseded_at = profile.received_at
        version = current.version + 1
    session.add(
        EtfProfileRow(
            id=uuid4(),
            symbol=profile.symbol,
            isin=profile.isin,
            name=profile.name,
            source=profile.source,
            received_at=profile.received_at,
            version=version,
            valid_from=profile.received_at,
            superseded_at=None,
            raw_response_id=raw_id,
        )
    )
    return True


def _versioned_profile(row: EtfProfileRow) -> VersionedEtfProfile:
    return VersionedEtfProfile(
        symbol=row.symbol,
        isin=row.isin,
        name=row.name,
        source=row.source,
        received_at=row.received_at,
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
    )
