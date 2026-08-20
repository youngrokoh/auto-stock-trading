from dataclasses import replace
from typing import TYPE_CHECKING, final

from sqlalchemy import select
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
    versioned_corporate_action,
)
from auto_stock_trading.adapters.database.market_data_rows import CorporateActionRow, InstrumentRow
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    VersionedCorporateAction,
)

if TYPE_CHECKING:
    from datetime import date, datetime

_CASH_ACTION_TYPES = (
    CorporateActionType.CASH_DIVIDEND.value,
    CorporateActionType.ETF_DISTRIBUTION.value,
)


@final
class PostgresExDateStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresExDateStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresExDateStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def symbols_missing_ex_date(self) -> tuple[str, ...]:
        """락일이 아직 없는 사실을 가진 종목만. 유니버스 전수를 돌리지 않는다."""
        statement = (
            select(InstrumentRow.symbol)
            .join(CorporateActionRow, CorporateActionRow.instrument_id == InstrumentRow.id)
            .where(
                CorporateActionRow.superseded_at.is_(None),
                CorporateActionRow.ex_date.is_(None),
                CorporateActionRow.record_date.is_not(None),
                CorporateActionRow.action_type.in_(_CASH_ACTION_TYPES),
                CorporateActionRow.lifecycle_status != CorporateActionLifecycle.CANCELLED.value,
                CorporateActionRow.quality_state != CorporateActionQuality.CONFLICT.value,
            )
            .distinct()
            .order_by(InstrumentRow.symbol)
        )
        async with self._sessions() as session:
            return tuple((await session.scalars(statement)).all())

    async def actions_missing_ex_date(
        self,
        symbol: str,
    ) -> tuple[VersionedCorporateAction, ...]:
        statement = (
            select(CorporateActionRow)
            .join(InstrumentRow, CorporateActionRow.instrument_id == InstrumentRow.id)
            .where(
                InstrumentRow.symbol == symbol,
                CorporateActionRow.superseded_at.is_(None),
                CorporateActionRow.ex_date.is_(None),
                CorporateActionRow.record_date.is_not(None),
                CorporateActionRow.action_type.in_(_CASH_ACTION_TYPES),
                CorporateActionRow.lifecycle_status != CorporateActionLifecycle.CANCELLED.value,
                CorporateActionRow.quality_state != CorporateActionQuality.CONFLICT.value,
            )
            .order_by(CorporateActionRow.record_date, CorporateActionRow.action_key)
        )
        async with self._sessions() as session:
            rows = tuple((await session.scalars(statement)).all())
        return tuple(versioned_corporate_action(row) for row in rows)

    async def confirm_ex_date(
        self,
        item: VersionedCorporateAction,
        ex_date: date,
        confirmed_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(
                CorporateActionRow,
                item.corporate_action_id,
                with_for_update=True,
            )
            if row is None or row.superseded_at is not None or row.ex_date is not None:
                return
            evidence = CorporateActionEvidence(
                action=replace(
                    item.action,
                    ex_date=ex_date,
                    quality=CorporateActionQuality.VERIFIED,
                    received_at=confirmed_at,
                ),
                action_key=item.action_key,
                instrument_id=row.instrument_id,
                raw_response_id=row.raw_response_id,
            )
            await save_corporate_action(session, evidence)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
