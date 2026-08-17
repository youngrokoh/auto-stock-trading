from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

import anyio
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auto_stock_trading.adapters.database.market_data_minute_bar_store import (
    PostgresMinuteBarStore,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    MinuteBarRow,
    SyncStatusRow,
)
from auto_stock_trading.domain.market_data.minute_bars import (
    InvalidMinuteBarError,
    MinuteBar,
    MinuteBarBundle,
    MinuteBarPage,
)
from auto_stock_trading.domain.market_data.models import (
    BarFinality,
    BrokerOperation,
    InstrumentTarget,
    ProductType,
    RawBrokerResponse,
)
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    type Sessions = async_sessionmaker[AsyncSession]
    type StoreScenario = Callable[[PostgresMinuteBarStore, Sessions], Awaitable[None]]

_SEOUL = ZoneInfo("Asia/Seoul")
_SYMBOL = "TESTMB"
_TARGET = InstrumentTarget(_SYMBOL, ProductType.ETF)
_TRADING_DATE = date(2026, 9, 21)
_FIRST_RECEIVED = datetime(2026, 9, 21, 6, 45, tzinfo=UTC)
_SECOND_RECEIVED = datetime(2026, 9, 21, 7, 0, tzinfo=UTC)
_MINUTE = timedelta(minutes=1)


def _bar_started(minute_offset: int) -> datetime:
    opens_at = datetime(2026, 9, 21, 9, 0, tzinfo=_SEOUL)
    return (opens_at + minute_offset * _MINUTE).astimezone(UTC)


def _bar(minute_offset: int, received_at: datetime, close: Decimal | None = None) -> MinuteBar:
    close_price = close if close is not None else Decimal(1000 + minute_offset)
    return MinuteBar(
        symbol=_SYMBOL,
        trading_date=_TRADING_DATE,
        bar_started_at=_bar_started(minute_offset),
        open_price=close_price - Decimal(2),
        high_price=close_price + Decimal(3),
        low_price=close_price - Decimal(3),
        close_price=close_price,
        volume=100 + minute_offset,
        cumulative_trading_value=Decimal(1_000_000 + minute_offset),
        source="KIS",
        received_at=received_at,
    )


def _bundle(bars: tuple[MinuteBar, ...], received_at: datetime) -> MinuteBarBundle:
    raw = RawBrokerResponse(
        operation=BrokerOperation.MINUTE_BARS,
        endpoint="/test-minute-bars",
        request_fingerprint=f"test:minute:{uuid4()}",
        received_at=received_at,
        payload_json="{}",
    )
    return MinuteBarBundle(
        target=_TARGET,
        trading_date=_TRADING_DATE,
        pages=(MinuteBarPage(raw, bars),),
        collected_at=received_at,
    )


def test_minute_bar_save_is_idempotent_for_identical_facts() -> None:
    async def scenario(store: PostgresMinuteBarStore, sessions: Sessions) -> None:
        # Given
        first = tuple(_bar(offset, _FIRST_RECEIVED) for offset in range(3))
        await store.save_minute_bundle(_bundle(first, _FIRST_RECEIVED))

        # When
        replay = tuple(replace(bar, received_at=_SECOND_RECEIVED) for bar in first)
        await store.save_minute_bundle(_bundle(replay, _SECOND_RECEIVED))

        # Then
        stored = await store.minute_bars(_SYMBOL, _TRADING_DATE)
        assert [item.bar.bar_started_at for item in stored] == [_bar_started(i) for i in range(3)]
        assert all(item.version == 1 for item in stored)
        assert all(item.finality is BarFinality.PENDING for item in stored)
        assert all(item.bar.received_at == _SECOND_RECEIVED for item in stored)
        assert await _row_count(sessions) == 3

    anyio.run(_run_scenario, scenario)


def test_minute_bar_correction_preserves_history_and_rejects_stale_evidence() -> None:
    async def scenario(store: PostgresMinuteBarStore, sessions: Sessions) -> None:
        # Given
        original = _bar(0, _FIRST_RECEIVED)
        await store.save_minute_bundle(_bundle((original,), _FIRST_RECEIVED))

        # When
        corrected = _bar(0, _SECOND_RECEIVED, close=Decimal(1234))
        await store.save_minute_bundle(_bundle((corrected,), _SECOND_RECEIVED))

        # Then
        stored = await store.minute_bars(_SYMBOL, _TRADING_DATE)
        assert len(stored) == 1
        assert stored[0].version == 2
        assert stored[0].bar.close_price == Decimal(1234)
        assert stored[0].finality is BarFinality.PENDING
        assert await _row_count(sessions) == 2
        stale = _bar(0, _FIRST_RECEIVED, close=Decimal(999))
        with pytest.raises(InvalidMinuteBarError):
            await store.save_minute_bundle(_bundle((stale,), _FIRST_RECEIVED))

    anyio.run(_run_scenario, scenario)


def test_minute_bar_confirmation_requires_matching_facts() -> None:
    async def scenario(store: PostgresMinuteBarStore, sessions: Sessions) -> None:
        # Given
        _ = sessions
        original = _bar(0, _FIRST_RECEIVED)
        await store.save_minute_bundle(_bundle((original,), _FIRST_RECEIVED))

        # When
        matching = replace(original, received_at=_SECOND_RECEIVED)
        mismatched = _bar(1, _SECOND_RECEIVED)
        confirmed = await store.confirm_minute_bar(matching, _SECOND_RECEIVED)
        missing = await store.confirm_minute_bar(mismatched, _SECOND_RECEIVED)

        # Then
        assert confirmed is True
        assert missing is False
        stored = await store.minute_bars(_SYMBOL, _TRADING_DATE)
        assert stored[0].finality is BarFinality.CONFIRMED
        assert stored[0].confirmed_at == _SECOND_RECEIVED

    anyio.run(_run_scenario, scenario)


def test_minute_bar_sync_status_records_success_and_failure() -> None:
    async def scenario(store: PostgresMinuteBarStore, sessions: Sessions) -> None:
        # When
        await store.mark_started(_TARGET, _FIRST_RECEIVED)
        await store.save_minute_bundle(_bundle((_bar(0, _FIRST_RECEIVED),), _FIRST_RECEIVED))
        succeeded = await _sync_row(sessions)
        await store.mark_failed(_TARGET, _SECOND_RECEIVED, "calendar_coverage_missing", "테스트")
        failed = await _sync_row(sessions)

        # Then
        assert succeeded is not None
        assert succeeded.state == "success"
        assert failed is not None
        assert failed.state == "failed"
        assert failed.error_code == "calendar_coverage_missing"

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: StoreScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        store = PostgresMinuteBarStore.from_connection(connection)
        try:
            await _seed_instrument(sessions)
            await scenario(store, sessions)
        finally:
            await store.close()
            await transaction.rollback()
    await engine.dispose()


async def _seed_instrument(sessions: Sessions) -> None:
    async with sessions.begin() as session:
        _ = await session.execute(delete(InstrumentRow).where(InstrumentRow.symbol == _SYMBOL))
        session.add(
            InstrumentRow(
                id=uuid4(),
                country="KR",
                exchange="XKRX",
                symbol=_SYMBOL,
                product_type="etf",
                currency="KRW",
                name="분봉 검증 종목",
                english_name=None,
                listed_on=None,
                delisted_on=None,
                trading_status="trading",
                source="KIS",
                source_as_of=_TRADING_DATE,
                created_at=_FIRST_RECEIVED,
                updated_at=_FIRST_RECEIVED,
            )
        )


async def _row_count(sessions: Sessions) -> int:
    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(MinuteBarRow)
            .join(InstrumentRow, MinuteBarRow.instrument_id == InstrumentRow.id)
            .where(InstrumentRow.symbol == _SYMBOL)
        )
    return count or 0


async def _sync_row(sessions: Sessions) -> SyncStatusRow | None:
    async with sessions() as session:
        return await session.scalar(
            select(SyncStatusRow).where(
                SyncStatusRow.source == "KIS",
                SyncStatusRow.operation == "minute_bars",
                SyncStatusRow.symbol == _SYMBOL,
            )
        )
