from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

import anyio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_corporate_action_repository import (
    CorporateActionEvidence,
    save_corporate_action,
)
from auto_stock_trading.adapters.database.market_data_exdate_store import PostgresExDateStore
from auto_stock_trading.adapters.database.market_data_rows import (
    CorporateActionRow,
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.application.corporate_action_exdates import ExDateResolver
from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarRawResponse,
    CalendarSessionKey,
    CalendarSource,
    ClosedMarketSession,
    MarketSessionType,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    TimePrecision,
)
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

    type Sessions = async_sessionmaker[AsyncSession]
    type ExDateScenario = Callable[[AsyncConnection, Sessions, UUID, UUID], Awaitable[None]]

_SEOUL = ZoneInfo("Asia/Seoul")
_SYMBOL = "TESTEX"
_RECEIVED_AT = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
_RESOLVED_AT = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)
_WEEK = (
    (date(2026, 9, 21), True),
    (date(2026, 9, 22), True),
    (date(2026, 9, 23), True),
    (date(2026, 9, 24), True),
    (date(2026, 9, 25), True),
    (date(2026, 9, 26), False),
    (date(2026, 9, 27), False),
)


def test_record_date_on_trading_day_confirms_previous_trading_day_ex_date() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_dividend(sessions, instrument_id, raw_id, record_date=date(2026, 9, 25))

        # When
        resolution = await _resolve(connection)

        # Then
        rows = await _rows(sessions)
        assert resolution.resolved == 1
        assert resolution.skipped == 0
        assert tuple(row.version for row in rows) == (1, 2)
        assert rows[0].superseded_at is not None
        assert rows[1].ex_date == date(2026, 9, 24)
        assert rows[1].quality_state == "verified"
        assert rows[1].available_at == rows[0].available_at
        assert rows[1].source_event_id == rows[0].source_event_id

    anyio.run(_run_scenario, scenario)


def test_record_date_on_closed_day_uses_last_settlement_trading_day() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_dividend(sessions, instrument_id, raw_id, record_date=date(2026, 9, 27))

        # When
        resolution = await _resolve(connection)

        # Then
        rows = await _rows(sessions)
        assert resolution.resolved == 1
        assert rows[1].ex_date == date(2026, 9, 24)

    anyio.run(_run_scenario, scenario)


def test_record_date_outside_calendar_coverage_is_skipped_fail_closed() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_dividend(sessions, instrument_id, raw_id, record_date=date(2031, 1, 31))

        # When
        resolution = await _resolve(connection)

        # Then
        rows = await _rows(sessions)
        assert resolution.resolved == 0
        assert resolution.skipped == 1
        assert tuple(row.version for row in rows) == (1,)
        assert rows[0].ex_date is None
        assert rows[0].quality_state == "pending"

    anyio.run(_run_scenario, scenario)


def test_resolution_is_idempotent_across_runs() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_dividend(sessions, instrument_id, raw_id, record_date=date(2026, 9, 25))
        _ = await _resolve(connection)

        # When
        second = await _resolve(connection)

        # Then
        rows = await _rows(sessions)
        assert second.resolved == 0
        assert second.skipped == 0
        assert tuple(row.version for row in rows) == (1, 2)

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: ExDateScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            instrument_id, raw_id = await _seed_instrument(sessions)
            await scenario(connection, sessions, instrument_id, raw_id)
        finally:
            await transaction.rollback()
    await engine.dispose()


async def _resolve(connection: AsyncConnection):  # noqa: ANN202
    calendar = PostgresMarketCalendarRepository.from_connection(connection)
    store = PostgresExDateStore.from_connection(connection)
    resolver = ExDateResolver(calendar=calendar, store=store)
    try:
        return await resolver.resolve(_SYMBOL, _RESOLVED_AT)
    finally:
        await calendar.close()
        await store.close()


async def _seed_calendar(connection: AsyncConnection) -> None:
    repository = PostgresMarketCalendarRepository.from_connection(connection)
    try:
        _ = await repository.save_all(tuple(_observation(day, is_open) for day, is_open in _WEEK))
    finally:
        await repository.close()


def _observation(day: date, is_open: bool) -> CalendarObservation:  # noqa: FBT001
    key = CalendarSessionKey("KR", "XKRX", day, MarketSessionType.REGULAR)
    if is_open:
        session = OpenMarketSession(
            key,
            SessionWindow(
                datetime.combine(day, time(9), _SEOUL).astimezone(UTC),
                datetime.combine(day, time(15, 30), _SEOUL).astimezone(UTC),
            ),
        )
    else:
        session = ClosedMarketSession(key, None)
    return CalendarObservation(
        session=session,
        exchange_timezone="Asia/Seoul",
        source=CalendarSource("KRX", "test-calendar", day),
        raw_response=CalendarRawResponse(
            endpoint="/test-calendar",
            request_fingerprint=f"test:calendar:{day}",
            received_at=_RECEIVED_AT,
            payload_json="{}",
        ),
        verification=PendingVerification(),
    )


async def _seed_instrument(sessions: Sessions) -> tuple[UUID, UUID]:
    instrument_id = uuid4()
    raw_id = uuid4()
    async with sessions.begin() as session:
        _ = await session.execute(delete(InstrumentRow).where(InstrumentRow.symbol == _SYMBOL))
        session.add(
            InstrumentRow(
                id=instrument_id,
                country="KR",
                exchange="XKRX",
                symbol=_SYMBOL,
                product_type="stock",
                currency="KRW",
                name="락일 검증 종목",
                english_name=None,
                listed_on=None,
                delisted_on=None,
                trading_status="trading",
                source="KIS",
                source_as_of=date(2026, 9, 28),
                created_at=_RECEIVED_AT,
                updated_at=_RECEIVED_AT,
            )
        )
        session.add(
            RawApiResponseRow(
                id=raw_id,
                source="DART",
                operation="corporate_actions",
                endpoint="/test",
                request_fingerprint=f"test:{raw_id}",
                received_at=_RECEIVED_AT,
                payload_json="{}",
            )
        )
    return instrument_id, raw_id


async def _seed_dividend(
    sessions: Sessions,
    instrument_id: UUID,
    raw_id: UUID,
    *,
    record_date: date,
) -> None:
    action = CorporateAction(
        action_type=CorporateActionType.CASH_DIVIDEND,
        lifecycle=CorporateActionLifecycle.ANNOUNCED,
        quality=CorporateActionQuality.PENDING,
        announced_at=None,
        announcement_date=date(2026, 9, 21),
        time_precision=TimePrecision.DATE,
        ex_date=None,
        effective_date=None,
        record_date=record_date,
        payment_date=None,
        share_multiplier=None,
        cash_amount=Decimal(100),
        currency="KRW",
        subscription_price=None,
        related_instrument_id=None,
        source="DART",
        source_event_id=f"test-{record_date.isoformat()}",
        source_reference="https://example.test/dividend",
        available_at=_RECEIVED_AT,
        received_at=_RECEIVED_AT,
    )
    async with sessions.begin() as session:
        await save_corporate_action(
            session,
            CorporateActionEvidence(
                action=action,
                action_key=uuid4(),
                instrument_id=instrument_id,
                raw_response_id=raw_id,
            ),
        )


async def _rows(sessions: Sessions) -> tuple[CorporateActionRow, ...]:
    async with sessions() as session:
        return tuple(
            (
                await session.scalars(
                    select(CorporateActionRow)
                    .join(InstrumentRow, CorporateActionRow.instrument_id == InstrumentRow.id)
                    .where(InstrumentRow.symbol == _SYMBOL)
                    .order_by(CorporateActionRow.version)
                )
            ).all()
        )


def test_symbols_missing_ex_dates_are_listed_for_universe_resolution() -> None:
    """유니버스 확정 패스는 미확정 사실이 있는 종목만 돌린다(200종목 전수 조회를 피한다)."""

    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        await _seed_calendar(connection)
        await _seed_dividend(sessions, instrument_id, raw_id, record_date=date(2026, 9, 25))
        store = PostgresExDateStore.from_connection(connection)

        pending = await store.symbols_missing_ex_date()
        assert _SYMBOL in pending

        _ = await _resolve(connection)

        assert _SYMBOL not in await store.symbols_missing_ex_date()

    anyio.run(_run_scenario, scenario)
