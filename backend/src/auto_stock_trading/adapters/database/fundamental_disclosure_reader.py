from typing import final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.fundamental_rows import DisclosureRow
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.domain.fundamentals.disclosures import Disclosure, DisclosureType


@final
class PostgresDisclosureReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresDisclosureReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresDisclosureReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def read_disclosures(self, symbol: str, limit: int) -> tuple[Disclosure, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(DisclosureRow)
                    .join(InstrumentRow, DisclosureRow.instrument_id == InstrumentRow.id)
                    .where(InstrumentRow.symbol == symbol)
                    .order_by(DisclosureRow.rcept_dt.desc(), DisclosureRow.rcept_no.desc())
                    .limit(limit)
                )
            ).all()
        return tuple(
            Disclosure(
                symbol=symbol,
                corp_code=row.corp_code,
                rcept_no=row.rcept_no,
                report_nm=row.report_nm,
                filer_name=row.flr_nm,
                receipt_date=row.rcept_dt,
                disclosure_type=DisclosureType(row.disclosure_type),
                received_at=row.received_at,
            )
            for row in rows
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
