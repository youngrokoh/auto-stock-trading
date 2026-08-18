from typing import TYPE_CHECKING, cast, final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import EtfNavRow, EtfProfileRow
from auto_stock_trading.domain.market_data.etf import (
    EtfListing,
    EtfNavSnapshot,
    VersionedEtfProfile,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@final
class PostgresEtfReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresEtfReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresEtfReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def read_etf_list(self) -> tuple[EtfListing, ...]:
        async with self._sessions() as session:
            # outerjoin이므로 EtfNavRow는 None일 수 있으나 SQLAlchemy 타입은 이를 못 담는다
            rows = cast(
                "Sequence[tuple[EtfProfileRow, EtfNavRow | None]]",
                (
                    await session.execute(
                        select(EtfProfileRow, EtfNavRow)
                        .outerjoin(EtfNavRow, EtfNavRow.symbol == EtfProfileRow.symbol)
                        .where(EtfProfileRow.superseded_at.is_(None))
                        .order_by(EtfProfileRow.symbol)
                    )
                )
                .tuples()
                .all(),
            )
        return tuple(
            EtfListing(
                profile=_profile(profile_row),
                snapshot=None if nav_row is None else _snapshot(nav_row),
            )
            for profile_row, nav_row in rows
        )

    async def read_etf(self, symbol: str) -> EtfListing | None:
        async with self._sessions() as session:
            row = cast(
                "tuple[EtfProfileRow, EtfNavRow | None] | None",
                (
                    await session.execute(
                        select(EtfProfileRow, EtfNavRow)
                        .outerjoin(EtfNavRow, EtfNavRow.symbol == EtfProfileRow.symbol)
                        .where(
                            EtfProfileRow.symbol == symbol,
                            EtfProfileRow.superseded_at.is_(None),
                        )
                        .limit(1)
                    )
                )
                .tuples()
                .first(),
            )
        if row is None:
            return None
        profile_row, nav_row = row
        return EtfListing(
            profile=_profile(profile_row),
            snapshot=None if nav_row is None else _snapshot(nav_row),
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def _profile(row: EtfProfileRow) -> VersionedEtfProfile:
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
