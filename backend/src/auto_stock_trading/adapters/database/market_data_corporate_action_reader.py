from typing import TYPE_CHECKING, final

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_corporate_action_repository import (
    read_corporate_action_history,
    read_corporate_actions_as_of,
    read_current_corporate_actions,
)

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.market_data.corporate_actions import (
        CorporateActionRange,
        VersionedCorporateAction,
    )


@final
class PostgresCorporateActionReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresCorporateActionReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresCorporateActionReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def read_current(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]:
        return await read_current_corporate_actions(self._sessions, query)

    async def read_history(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]:
        return await read_corporate_action_history(self._sessions, query)

    async def read_as_of(
        self,
        query: CorporateActionRange,
        knowledge_cutoff_at: datetime,
    ) -> tuple[VersionedCorporateAction, ...]:
        return await read_corporate_actions_as_of(self._sessions, query, knowledge_cutoff_at)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
