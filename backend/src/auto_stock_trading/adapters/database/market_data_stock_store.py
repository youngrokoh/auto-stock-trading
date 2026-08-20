"""종목 유니버스 버전 저장소. 마스터 수집이 종목 행까지 함께 만든다."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_listed_share_repository import (
    save_listed_share_count,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.adapters.database.market_data_statements import (
    instrument_id_for,
    quote_snapshot_upsert,
)
from auto_stock_trading.adapters.database.market_data_sync_statements import (
    SyncTarget,
    sync_failed,
    sync_started,
    sync_succeeded,
)
from auto_stock_trading.adapters.database.reference_stock_rows import StockProfileRow
from auto_stock_trading.domain.market_data.models import (
    InstrumentIdentityConflictError,
    ProductType,
)
from auto_stock_trading.domain.market_data.stocks import VersionedStockProfile

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from auto_stock_trading.domain.market_data.models import (
        QuoteSnapshotObservation,
        RawBrokerResponse,
    )
    from auto_stock_trading.domain.market_data.stocks import StockMasterBundle, StockProfile

_SOURCE: Final = "KIS"
_MASTER_OPERATION: Final = "stock_master"
_COUNTRY: Final = "KR"
_EXCHANGE: Final = "XKRX"
_CURRENCY: Final = "KRW"
_ACTIVE: Final = "active"
_SEOUL_SOURCE: Final = "KIS_MASTER"


@final
class PostgresStockStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresStockStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresStockStore:
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

    async def save_master_bundle(self, bundle: StockMasterBundle) -> int:
        """새 버전 수를 돌려준다. 같은 값 재수집은 0이다."""
        async with self._sessions.begin() as session:
            raw_id = _add_raw_row(session, bundle.raw)
            saved = 0
            for profile in bundle.profiles:
                await _reject_product_type_conflict(session, profile.symbol)
                _ = await session.execute(_instrument_upsert(profile, bundle.collected_at))
                if await _save_profile(session, profile, raw_id):
                    saved += 1
            return saved

    async def save_quote_snapshot(self, observation: QuoteSnapshotObservation) -> None:
        """종목당 최신 시세 한 행을 유지하고 상장주식수는 버전 사실로 남긴다."""
        quote = observation.quote
        instrument_id = instrument_id_for(
            country=_COUNTRY,
            exchange=_EXCHANGE,
            symbol=quote.symbol,
            product_type=ProductType.STOCK,
            currency=_CURRENCY,
        )
        async with self._sessions.begin() as session:
            raw_id = uuid4()
            session.add(
                RawApiResponseRow(
                    id=raw_id,
                    source=_SOURCE,
                    operation=observation.raw.operation.value,
                    endpoint=observation.raw.endpoint,
                    request_fingerprint=observation.raw.request_fingerprint,
                    received_at=observation.raw.received_at,
                    payload_json=observation.raw.payload_json,
                )
            )
            _ = await session.execute(quote_snapshot_upsert(quote, instrument_id, raw_id))
            await save_listed_share_count(
                session,
                observation.listed_shares,
                instrument_id,
                raw_id,
            )

    async def sector(self, symbol: str) -> str | None:
        """업종 사실이 없으면 None이다. 위험검사는 그때 미분류로 판정한다."""
        async with self._sessions() as session:
            return await session.scalar(
                select(StockProfileRow.sector_code).where(
                    StockProfileRow.symbol == symbol,
                    StockProfileRow.superseded_at.is_(None),
                )
            )

    async def universe_symbols(self) -> tuple[str, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(StockProfileRow.symbol)
                .where(StockProfileRow.superseded_at.is_(None))
                .order_by(StockProfileRow.symbol)
            )
            return tuple(rows.all())

    async def profiles(self) -> tuple[VersionedStockProfile, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(StockProfileRow)
                .where(StockProfileRow.superseded_at.is_(None))
                .order_by(StockProfileRow.symbol)
            )
            return tuple(_versioned_profile(row) for row in rows.all())

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def _add_raw_row(session: AsyncSession, raw: RawBrokerResponse) -> UUID:
    raw_id = uuid4()
    session.add(
        RawApiResponseRow(
            id=raw_id,
            source=_SOURCE,
            operation=_MASTER_OPERATION,
            endpoint=raw.endpoint,
            request_fingerprint=raw.request_fingerprint,
            received_at=raw.received_at,
            payload_json=raw.payload_json,
        )
    )
    return raw_id


async def _reject_product_type_conflict(session: AsyncSession, symbol: str) -> None:
    """이미 다른 상품유형으로 저장된 코드는 주식 종목 행을 새로 만들지 않는다."""
    stored = await session.scalar(
        select(InstrumentRow.product_type).where(
            InstrumentRow.country == _COUNTRY,
            InstrumentRow.exchange == _EXCHANGE,
            InstrumentRow.symbol == symbol,
            InstrumentRow.currency == _CURRENCY,
            InstrumentRow.product_type != ProductType.STOCK.value,
        )
    )
    if stored is not None:
        raise InstrumentIdentityConflictError(
            symbol=symbol,
            stored=stored,
            requested=ProductType.STOCK.value,
        )


def _instrument_upsert(profile: StockProfile, now: datetime):  # noqa: ANN202
    """이름·출처만 갱신한다. 거래 상태는 마스터에 없으므로 덮어쓰지 않는다."""
    statement = insert(InstrumentRow).values(
        id=instrument_id_for(
            country=_COUNTRY,
            exchange=_EXCHANGE,
            symbol=profile.symbol,
            product_type=ProductType.STOCK,
            currency=_CURRENCY,
        ),
        country=_COUNTRY,
        exchange=_EXCHANGE,
        symbol=profile.symbol,
        product_type=ProductType.STOCK.value,
        currency=_CURRENCY,
        name=profile.name,
        english_name=None,
        listed_on=None,
        delisted_on=None,
        trading_status=_ACTIVE,
        source=_SEOUL_SOURCE,
        source_as_of=profile.received_at.date(),
        created_at=now,
        updated_at=now,
    )
    return statement.on_conflict_do_update(
        constraint="uq_instrument_identity",
        set_={
            "name": profile.name,
            "source": _SEOUL_SOURCE,
            "source_as_of": profile.received_at.date(),
            "updated_at": now,
        },
    )


async def _save_profile(session: AsyncSession, profile: StockProfile, raw_id: UUID) -> bool:
    current = await session.scalar(
        select(StockProfileRow)
        .where(
            StockProfileRow.symbol == profile.symbol,
            StockProfileRow.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current is not None and _same_fact(current, profile):
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
        StockProfileRow(
            id=uuid4(),
            symbol=profile.symbol,
            isin=profile.isin,
            name=profile.name,
            sector_code=profile.sector_code,
            source=profile.source,
            received_at=profile.received_at,
            version=version,
            valid_from=profile.received_at,
            superseded_at=None,
            raw_response_id=raw_id,
        )
    )
    return True


def _same_fact(current: StockProfileRow, profile: StockProfile) -> bool:
    return (
        current.isin == profile.isin
        and current.name == profile.name
        and current.sector_code == profile.sector_code
    )


def _versioned_profile(row: StockProfileRow) -> VersionedStockProfile:
    return VersionedStockProfile(
        symbol=row.symbol,
        isin=row.isin,
        name=row.name,
        sector_code=row.sector_code,
        source=row.source,
        received_at=row.received_at,
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
    )
