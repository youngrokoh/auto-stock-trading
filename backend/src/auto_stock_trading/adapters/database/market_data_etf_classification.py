"""ETF 추종 지수 버전 사실의 저장과 조회(ADR-0021).

`market_data_etf_store`는 250 pure-LOC 검토 기준에 가까워서 분류 쓰기·읽기는 여기에 둔다.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import EtfNavRow
from auto_stock_trading.adapters.database.reference_etf_rows import EtfIndexClassificationRow
from auto_stock_trading.domain.market_data.etf import EtfNavSnapshot
from auto_stock_trading.domain.market_data.etf_classification import (
    EtfIndexClassification,
    VersionedEtfIndexClassification,
    classification_sector,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID


async def save_etf_index_classification(
    session: AsyncSession,
    snapshot: EtfNavSnapshot,
    raw_response_id: UUID,
) -> bool:
    """NAV 관측에서 분류 사실을 갱신한다. 새 버전이 생기면 True다.

    같은 값(지수·추적배수) 재관측은 증거만 갱신한다. 값이 바뀌면 이전 버전을 보존한 새 버전이다.
    """
    current = await session.scalar(
        select(EtfIndexClassificationRow).where(
            EtfIndexClassificationRow.symbol == snapshot.symbol,
            EtfIndexClassificationRow.source == snapshot.source,
            EtfIndexClassificationRow.superseded_at.is_(None),
        )
    )
    if (
        current is not None
        and current.index_name == snapshot.index_name
        and current.tracking_multiple == snapshot.tracking_multiple
    ):
        current.as_of = snapshot.as_of
        current.received_at = snapshot.received_at
        current.raw_response_id = raw_response_id
        return False
    version = 1
    if current is not None:
        current.superseded_at = snapshot.received_at
        version = current.version + 1
        await session.flush()
    session.add(
        EtfIndexClassificationRow(
            id=uuid4(),
            symbol=snapshot.symbol,
            index_name=snapshot.index_name,
            tracking_multiple=snapshot.tracking_multiple,
            source=snapshot.source,
            as_of=snapshot.as_of,
            received_at=snapshot.received_at,
            version=version,
            valid_from=snapshot.received_at,
            superseded_at=None,
            raw_response_id=raw_response_id,
        )
    )
    return True


async def backfill_etf_index_classification(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[int, int]:
    """이미 저장된 NAV 스냅샷에서 분류 사실을 만든다. (관측 수, 새 버전 수)를 돌려준다.

    사실이 도입되기 전에 수집된 스냅샷은 갱신 경로를 지나지 않았다. 스냅샷의 as_of·received_at·
    원문 응답을 그대로 증거로 쓰므로 새로 관측한 척하지 않는다 — 다음 전수 수집이 이를 갱신한다.
    """
    async with sessions.begin() as session:
        rows = (await session.scalars(select(EtfNavRow).order_by(EtfNavRow.symbol))).all()
        created = 0
        for row in rows:
            if await save_etf_index_classification(session, _snapshot(row), row.raw_response_id):
                created += 1
        return len(rows), created


def _snapshot(row: EtfNavRow) -> EtfNavSnapshot:
    return EtfNavSnapshot(
        symbol=row.symbol,
        price=row.price,
        change_percent=row.change_percent,
        volume=row.volume,
        previous_volume=row.previous_volume,
        nav=row.nav,
        divergence_rate=row.divergence_rate,
        tracking_error=row.tracking_error,
        tracking_multiple=row.tracking_multiple,
        net_asset_total=row.net_asset_total,
        listed_shares=row.listed_shares,
        manager=row.manager,
        index_name=row.index_name,
        listing_date=row.listing_date,
        currency=row.currency,
        source=row.source,
        as_of=row.as_of,
        received_at=row.received_at,
    )


def _now() -> datetime:
    return datetime.now(UTC)


@final
class PostgresEtfClassificationSource:
    """`SectorSource`의 ETF 쪽 구현. 사실이 없거나 규칙에 걸리면 None — 미분류로 남는다."""

    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._engine = engine
        self._sessions = sessions
        self._clock = clock

    @classmethod
    def from_url(cls, database_url: str) -> PostgresEtfClassificationSource:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(
        cls,
        connection: AsyncConnection,
        clock: Callable[[], datetime] = _now,
    ) -> PostgresEtfClassificationSource:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions, clock)

    async def sector(self, symbol: str) -> str | None:
        current = await self.current(symbol)
        if current is None:
            return None
        return classification_sector(_fact(current), now=self._clock())

    async def current(self, symbol: str) -> VersionedEtfIndexClassification | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(EtfIndexClassificationRow).where(
                    EtfIndexClassificationRow.symbol == symbol,
                    EtfIndexClassificationRow.superseded_at.is_(None),
                )
            )
        return None if row is None else _versioned(row)

    async def history(self, symbol: str) -> tuple[VersionedEtfIndexClassification, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(EtfIndexClassificationRow)
                .where(EtfIndexClassificationRow.symbol == symbol)
                .order_by(EtfIndexClassificationRow.version)
            )
            return tuple(_versioned(row) for row in rows.all())

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def _fact(row: VersionedEtfIndexClassification) -> EtfIndexClassification:
    return EtfIndexClassification(
        symbol=row.symbol,
        index_name=row.index_name,
        tracking_multiple=row.tracking_multiple,
        source=row.source,
        as_of=row.as_of,
        received_at=row.received_at,
    )


def _versioned(row: EtfIndexClassificationRow) -> VersionedEtfIndexClassification:
    return VersionedEtfIndexClassification(
        symbol=row.symbol,
        index_name=row.index_name,
        tracking_multiple=row.tracking_multiple,
        source=row.source,
        as_of=row.as_of,
        received_at=row.received_at,
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
    )
