from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_calendar_mapping import (
    calendar_facts_match,
    calendar_record,
    mark_calendar_conflict,
    new_calendar_row,
    refresh_calendar_from_primary,
    refresh_calendar_from_secondary,
    supersede_calendar,
)
from auto_stock_trading.adapters.database.market_calendar_rows import MarketCalendarRow
from auto_stock_trading.adapters.database.market_calendar_statements import (
    calendar_conflict_upsert,
)
from auto_stock_trading.adapters.database.market_data_rows import RawApiResponseRow
from auto_stock_trading.domain.market_data.calendar import (
    CalendarInvariant,
    CalendarObservation,
    CalendarScheduleDecision,
    CalendarSessionKey,
    CalendarSessionRange,
    InvalidMarketCalendarError,
    MarketCalendarRecord,
    MarketSessionStatus,
    calendar_schedule_decision,
    calendar_session_key,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

_PRIMARY_SOURCE: Final = "KRX"


@final
class PostgresMarketCalendarRepository:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresMarketCalendarRepository:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresMarketCalendarRepository:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def save(self, observation: CalendarObservation) -> MarketCalendarRecord:
        key = calendar_session_key(observation.session)
        async with self._sessions.begin() as session:
            raw_response_id = uuid4()
            raw = observation.raw_response
            session.add(
                RawApiResponseRow(
                    id=raw_response_id,
                    source=observation.source.name,
                    operation="market_calendar",
                    endpoint=raw.endpoint,
                    request_fingerprint=raw.request_fingerprint,
                    received_at=raw.received_at,
                    payload_json=raw.payload_json,
                )
            )
            current = await session.scalar(_current_session_statement(key).with_for_update())
            lower_priority_conflict = _is_lower_priority_conflict(current, observation)
            row = self._merge_observation(current, observation, raw_response_id)
            if current is None or row is not current:
                session.add(row)
            if lower_priority_conflict:
                _ = await session.execute(calendar_conflict_upsert(observation))
            await session.flush()
            return calendar_record(row)

    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(_current_session_statement(key))
        return calendar_record(row) if row is not None else None

    async def sessions(
        self,
        query: CalendarSessionRange,
    ) -> tuple[MarketCalendarRecord, ...]:
        statement = (
            select(MarketCalendarRow)
            .where(
                MarketCalendarRow.country == query.country,
                MarketCalendarRow.exchange == query.exchange,
                MarketCalendarRow.trading_date >= query.start_date,
                MarketCalendarRow.trading_date <= query.end_date,
                MarketCalendarRow.session_type == query.session_type.value,
                MarketCalendarRow.superseded_at.is_(None),
            )
            .order_by(MarketCalendarRow.trading_date)
        )
        async with self._sessions() as session:
            rows = tuple((await session.scalars(statement)).all())
        return tuple(calendar_record(row) for row in rows)

    async def next_open_date(self, key: CalendarSessionKey) -> date | None:
        statement = _open_date_statement(key).where(
            MarketCalendarRow.trading_date > key.trading_date
        )
        async with self._sessions() as session:
            return await session.scalar(statement.order_by(MarketCalendarRow.trading_date))

    async def previous_open_date(self, key: CalendarSessionKey) -> date | None:
        statement = _open_date_statement(key).where(
            MarketCalendarRow.trading_date < key.trading_date
        )
        async with self._sessions() as session:
            return await session.scalar(statement.order_by(MarketCalendarRow.trading_date.desc()))

    async def schedule_decision(
        self,
        key: CalendarSessionKey,
        decision_at: datetime,
    ) -> CalendarScheduleDecision:
        return calendar_schedule_decision(await self.session(key), decision_at)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    @staticmethod
    def _merge_observation(
        current: MarketCalendarRow | None,
        observation: CalendarObservation,
        raw_response_id: UUID,
    ) -> MarketCalendarRow:
        if current is None:
            return new_calendar_row(observation, raw_response_id, 1)
        if calendar_facts_match(current, observation):
            if observation.source.name == _PRIMARY_SOURCE or current.source != _PRIMARY_SOURCE:
                refresh_calendar_from_primary(current, observation, raw_response_id)
            else:
                refresh_calendar_from_secondary(current, observation, raw_response_id)
            return current
        if current.source == _PRIMARY_SOURCE and observation.source.name != _PRIMARY_SOURCE:
            mark_calendar_conflict(current, observation, raw_response_id)
            return current
        received_at = observation.raw_response.received_at
        if received_at <= current.valid_from:
            raise InvalidMarketCalendarError(CalendarInvariant.VALIDITY)
        supersede_calendar(current, received_at)
        return new_calendar_row(observation, raw_response_id, current.version + 1)


def _current_session_statement(key: CalendarSessionKey) -> Select[tuple[MarketCalendarRow]]:
    return select(MarketCalendarRow).where(
        MarketCalendarRow.country == key.country,
        MarketCalendarRow.exchange == key.exchange,
        MarketCalendarRow.trading_date == key.trading_date,
        MarketCalendarRow.session_type == key.session_type.value,
        MarketCalendarRow.superseded_at.is_(None),
    )


def _open_date_statement(key: CalendarSessionKey) -> Select[tuple[date]]:
    return select(MarketCalendarRow.trading_date).where(
        MarketCalendarRow.country == key.country,
        MarketCalendarRow.exchange == key.exchange,
        MarketCalendarRow.session_type == key.session_type.value,
        MarketCalendarRow.session_status.in_(
            (MarketSessionStatus.OPEN.value, MarketSessionStatus.SHORTENED.value)
        ),
        MarketCalendarRow.superseded_at.is_(None),
    )


def _is_lower_priority_conflict(
    current: MarketCalendarRow | None,
    observation: CalendarObservation,
) -> bool:
    return (
        current is not None
        and current.source == _PRIMARY_SOURCE
        and observation.source.name != _PRIMARY_SOURCE
        and not calendar_facts_match(current, observation)
    )
