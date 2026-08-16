from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import anyio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_calendar_rows import MarketCalendarRow
from auto_stock_trading.adapters.database.market_data_rows import (
    RawApiResponseRow,
    SyncStatusRow,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarRawResponse,
    CalendarScheduleDecision,
    CalendarSessionKey,
    CalendarSessionRange,
    CalendarSource,
    ClosedMarketSession,
    ConfirmedVerification,
    MarketSessionStatus,
    MarketSessionType,
    OpenMarketSession,
    SessionWindow,
    ShortenedMarketSession,
    calendar_session_status,
)
from auto_stock_trading.settings.runtime import Settings

type CalendarScenario = Callable[
    [PostgresMarketCalendarRepository, AsyncConnection],
    Awaitable[None],
]

_SEOUL = ZoneInfo("Asia/Seoul")


def test_repository_preserves_versions_and_reuses_identical_facts() -> None:
    async def scenario(
        repository: PostgresMarketCalendarRepository,
        connection: AsyncConnection,
    ) -> None:
        # Given
        trading_date = date(2026, 8, 24)
        first = _observation(_open_session(trading_date), hour=5)
        repeated = _observation(_open_session(trading_date), hour=6)
        corrected = _observation(_shortened_session(trading_date), hour=7)

        # When
        saved = (
            await repository.save(first),
            await repository.save(repeated),
            await repository.save(corrected),
        )

        # Then
        versions = tuple(
            (
                await connection.scalars(
                    select(MarketCalendarRow.version)
                    .where(MarketCalendarRow.trading_date == trading_date)
                    .order_by(MarketCalendarRow.version)
                )
            ).all()
        )
        superseded_times = tuple(
            (
                await connection.scalars(
                    select(MarketCalendarRow.superseded_at)
                    .where(MarketCalendarRow.trading_date == trading_date)
                    .order_by(MarketCalendarRow.version)
                )
            ).all()
        )
        current = await repository.session(_key(trading_date))
        raw_count = await connection.scalar(
            select(func.count(RawApiResponseRow.id)).where(
                RawApiResponseRow.request_fingerprint.like(f"calendar:{trading_date}:%")
            )
        )

        assert tuple(record.version for record in saved) == (1, 1, 2)
        assert versions == (1, 2)
        assert superseded_times[0] is not None
        assert superseded_times[1] is None
        assert current is not None
        assert calendar_session_status(current.session) is MarketSessionStatus.SHORTENED
        assert raw_count == 3

    anyio.run(_run_scenario, scenario)


def test_repository_queries_range_and_neighboring_open_dates() -> None:
    async def scenario(
        repository: PostgresMarketCalendarRepository,
        _: AsyncConnection,
    ) -> None:
        # Given
        closed_date = date(2026, 8, 25)
        open_date = date(2026, 8, 26)
        shortened_date = date(2026, 8, 27)
        for observation in (
            _observation(ClosedMarketSession(_key(closed_date), "fixture holiday"), hour=5),
            _observation(_open_session(open_date), hour=5),
            _observation(_shortened_session(shortened_date), hour=5),
        ):
            _saved_record = await repository.save(observation)

        # When
        sessions = await repository.sessions(
            CalendarSessionRange("KR", "XKRX", closed_date, shortened_date)
        )
        next_date = await repository.next_open_date(_key(closed_date))
        previous_date = await repository.previous_open_date(_key(date(2026, 8, 28)))

        # Then
        assert tuple(record.session.key.trading_date for record in sessions) == (
            closed_date,
            open_date,
            shortened_date,
        )
        assert next_date == open_date
        assert previous_date == shortened_date

    anyio.run(_run_scenario, scenario)


def test_lower_priority_conflict_preserves_krx_fact_and_blocks_schedule() -> None:
    async def scenario(
        repository: PostgresMarketCalendarRepository,
        connection: AsyncConnection,
    ) -> None:
        # Given
        trading_date = date(2026, 8, 28)
        _initial_record = await repository.save(_observation(_open_session(trading_date), hour=5))

        # When
        conflicted = await repository.save(
            _observation(
                ClosedMarketSession(_key(trading_date), "KIS fixture conflict"),
                hour=6,
                source="KIS",
            )
        )

        # Then
        versions = tuple(
            (
                await connection.scalars(
                    select(MarketCalendarRow.version).where(
                        MarketCalendarRow.trading_date == trading_date
                    )
                )
            ).all()
        )
        sources = tuple(
            (
                await connection.scalars(
                    select(MarketCalendarRow.source).where(
                        MarketCalendarRow.trading_date == trading_date
                    )
                )
            ).all()
        )
        sync_state = await connection.scalar(
            select(SyncStatusRow.state).where(
                SyncStatusRow.source == "KIS",
                SyncStatusRow.operation == "market_calendar",
                SyncStatusRow.symbol == f"XKRX:{trading_date}",
            )
        )
        sync_error_code = await connection.scalar(
            select(SyncStatusRow.error_code).where(
                SyncStatusRow.source == "KIS",
                SyncStatusRow.operation == "market_calendar",
                SyncStatusRow.symbol == f"XKRX:{trading_date}",
            )
        )
        decision = await repository.schedule_decision(
            _key(trading_date),
            _window(trading_date, time(15, 30)).opens_at,
        )

        assert versions == (1,)
        assert sources == ("KRX",)
        assert isinstance(conflicted.session, OpenMarketSession)
        assert decision is CalendarScheduleDecision.CONFLICT
        assert sync_state == "failed"
        assert sync_error_code == "calendar_source_conflict"

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: CalendarScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        repository = PostgresMarketCalendarRepository.from_connection(connection)
        try:
            await scenario(repository, connection)
        finally:
            await repository.close()
            await transaction.rollback()
    await engine.dispose()


def _key(trading_date: date) -> CalendarSessionKey:
    return CalendarSessionKey("KR", "XKRX", trading_date, MarketSessionType.REGULAR)


def _open_session(trading_date: date) -> OpenMarketSession:
    return OpenMarketSession(_key(trading_date), _window(trading_date, time(15, 30)))


def _shortened_session(trading_date: date) -> ShortenedMarketSession:
    return ShortenedMarketSession(
        _key(trading_date),
        _window(trading_date, time(14, 30)),
        "fixture shortened session",
    )


def _window(trading_date: date, closes_at: time) -> SessionWindow:
    return SessionWindow(
        datetime.combine(trading_date, time(9), _SEOUL).astimezone(UTC),
        datetime.combine(trading_date, closes_at, _SEOUL).astimezone(UTC),
    )


def _observation(
    session: OpenMarketSession | ClosedMarketSession | ShortenedMarketSession,
    *,
    hour: int,
    source: str = "KRX",
) -> CalendarObservation:
    trading_date = session.key.trading_date
    received_at = datetime.combine(trading_date, time(hour), _SEOUL).astimezone(UTC)
    status = calendar_session_status(session)
    return CalendarObservation(
        session=session,
        exchange_timezone="Asia/Seoul",
        source=CalendarSource(source, "fixture-calendar", trading_date),
        raw_response=CalendarRawResponse(
            endpoint="fixture://market-calendar",
            request_fingerprint=f"calendar:{trading_date}:{hour}:{status.value}",
            received_at=received_at,
            payload_json='{"fixture":true}',
        ),
        verification=ConfirmedVerification(received_at),
    )
