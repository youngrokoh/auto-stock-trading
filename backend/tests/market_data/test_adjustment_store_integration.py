from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import anyio
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_adjustment_records import (
    AdjustmentRequest,
)
from auto_stock_trading.adapters.database.market_data_adjustment_store import (
    PostgresAdjustmentStore,
)
from auto_stock_trading.adapters.database.market_data_corporate_action_repository import (
    CorporateActionEvidence,
    save_corporate_action,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    MarketBarRow,
    RawApiResponseRow,
    SyncStatusRow,
)
from auto_stock_trading.domain.market_data.adjustments import (
    ADJUSTMENT_ALGORITHM_VERSION,
    AdjustmentError,
    AdjustmentFailure,
    AdjustmentMethod,
)
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

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

    type Sessions = async_sessionmaker[AsyncSession]
    type StoreScenario = Callable[[AsyncConnection, Sessions, UUID, UUID], Awaitable[None]]

_SEOUL = ZoneInfo("Asia/Seoul")
_SYMBOL = "TESTAD"
_WEEK = (
    (date(2026, 9, 21), True),
    (date(2026, 9, 22), True),
    (date(2026, 9, 23), True),
    (date(2026, 9, 24), True),
    (date(2026, 9, 25), True),
    (date(2026, 9, 26), False),
    (date(2026, 9, 27), False),
)
_OPEN_DATES = tuple(day for day, is_open in _WEEK if is_open)
_ANNOUNCED_AT = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
_CORRECTED_AT = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)
_GENERATED_AT = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)


def _request(
    method: AdjustmentMethod = AdjustmentMethod.TOTAL_RETURN,
    knowledge_cutoff_at: datetime = _GENERATED_AT,
) -> AdjustmentRequest:
    return AdjustmentRequest(
        symbol=_SYMBOL,
        method=method,
        range_start=_OPEN_DATES[0],
        price_cutoff_date=_OPEN_DATES[-1],
        knowledge_cutoff_at=knowledge_cutoff_at,
    )


def test_total_return_dataset_is_published_with_lineage() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_bars(sessions, instrument_id, raw_id)
        _ = await _seed_dividend(sessions, instrument_id, raw_id, cash_amount=Decimal(30))

        # When
        record = await _build(connection, _request())

        # Then
        store = PostgresAdjustmentStore.from_connection(connection)
        adjusted = await store.read_adjusted_bars(record.dataset_id)
        actions = await store.read_dataset_actions(record.dataset_id)
        latest = await store.read_latest_published(_SYMBOL, AdjustmentMethod.TOTAL_RETURN)
        await store.close()
        assert record.status == "published"
        assert record.algorithm_version == ADJUSTMENT_ALGORITHM_VERSION
        assert len(record.input_bar_version_hash) == 64
        assert len(adjusted) == 5
        by_date = {item.trading_date: item for item in adjusted}
        assert by_date[date(2026, 9, 23)].close_price == Decimal("990.00000000")
        assert by_date[date(2026, 9, 23)].price_factor == Decimal("0.9705882352941176")
        assert by_date[date(2026, 9, 24)].close_price == Decimal("1030.00000000")
        assert by_date[date(2026, 9, 24)].price_factor == Decimal("1.0000000000000000")
        assert by_date[date(2026, 9, 21)].volume == 100
        assert len(actions) == 1
        assert actions[0].event_date == date(2026, 9, 24)
        assert actions[0].event_price_factor == Decimal("0.9705882352941176")
        assert latest is not None
        assert latest.dataset_id == record.dataset_id

    anyio.run(_run_scenario, scenario)


def test_same_inputs_reuse_the_published_dataset() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_bars(sessions, instrument_id, raw_id)
        _ = await _seed_dividend(sessions, instrument_id, raw_id, cash_amount=Decimal(30))
        first = await _build(connection, _request())

        # When
        second = await _build(connection, _request())

        # Then
        store = PostgresAdjustmentStore.from_connection(connection)
        datasets = await store.read_datasets_for_symbol(_SYMBOL)
        await store.close()
        assert second.dataset_id == first.dataset_id
        assert len(datasets) == 1

    anyio.run(_run_scenario, scenario)


def test_knowledge_cutoff_selects_action_versions() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_bars(sessions, instrument_id, raw_id)
        original = await _seed_dividend(sessions, instrument_id, raw_id, cash_amount=Decimal(30))
        await _seed_correction(sessions, instrument_id, raw_id, original, Decimal(51))

        # When
        before = await _build(
            connection,
            _request(knowledge_cutoff_at=_ANNOUNCED_AT),
        )
        after = await _build(connection, _request(knowledge_cutoff_at=_GENERATED_AT))

        # Then
        store = PostgresAdjustmentStore.from_connection(connection)
        before_bars = await store.read_adjusted_bars(before.dataset_id)
        after_bars = await store.read_adjusted_bars(after.dataset_id)
        await store.close()
        assert before.dataset_id != after.dataset_id
        assert before.action_version_hash != after.action_version_hash
        before_by_date = {item.trading_date: item for item in before_bars}
        after_by_date = {item.trading_date: item for item in after_bars}
        assert before_by_date[date(2026, 9, 23)].close_price == Decimal("990.00000000")
        assert after_by_date[date(2026, 9, 23)].close_price == Decimal("969.00000000")

    anyio.run(_run_scenario, scenario)


def test_bar_correction_creates_new_dataset_and_preserves_the_old_one() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_bars(sessions, instrument_id, raw_id)
        first = await _build(connection, _request(AdjustmentMethod.SPLIT_ADJUSTED))
        await _correct_bar(sessions, instrument_id, raw_id, date(2026, 9, 25))

        # When
        second = await _build(connection, _request(AdjustmentMethod.SPLIT_ADJUSTED))

        # Then
        store = PostgresAdjustmentStore.from_connection(connection)
        datasets = await store.read_datasets_for_symbol(_SYMBOL)
        old_bars = await store.read_adjusted_bars(first.dataset_id)
        await store.close()
        assert second.dataset_id != first.dataset_id
        assert second.input_bar_version_hash != first.input_bar_version_hash
        statuses = {item.dataset_id: item.status for item in datasets}
        assert statuses[first.dataset_id] == "superseded"
        assert statuses[second.dataset_id] == "published"
        assert len(old_bars) == 5

    anyio.run(_run_scenario, scenario)


def test_unconfirmed_bar_records_failed_dataset_and_sync_error() -> None:
    async def scenario(
        connection: AsyncConnection,
        sessions: Sessions,
        instrument_id: UUID,
        raw_id: UUID,
    ) -> None:
        # Given
        await _seed_calendar(connection)
        await _seed_bars(sessions, instrument_id, raw_id, pending_date=date(2026, 9, 24))

        # When
        with pytest.raises(AdjustmentError) as error:
            _ = await _build(connection, _request(AdjustmentMethod.SPLIT_ADJUSTED))

        # Then
        store = PostgresAdjustmentStore.from_connection(connection)
        datasets = await store.read_datasets_for_symbol(_SYMBOL)
        await store.close()
        status = await _sync_row(sessions)
        assert error.value.failure is AdjustmentFailure.UNCONFIRMED_BAR
        assert len(datasets) == 1
        assert datasets[0].status == "failed"
        assert datasets[0].failure_code == "unconfirmed_bar_in_range"
        assert status is not None
        assert status.state == "failed"

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
        try:
            instrument_id, raw_id = await _seed_instrument(sessions)
            await scenario(connection, sessions, instrument_id, raw_id)
        finally:
            await transaction.rollback()
    await engine.dispose()


async def _build(connection: AsyncConnection, request: AdjustmentRequest):  # noqa: ANN202
    store = PostgresAdjustmentStore.from_connection(connection)
    try:
        return await store.build_dataset(request, _GENERATED_AT)
    finally:
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
            received_at=_ANNOUNCED_AT,
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
                name="수정주가 검증 종목",
                english_name=None,
                listed_on=None,
                delisted_on=None,
                trading_status="trading",
                source="KIS",
                source_as_of=date(2026, 9, 28),
                created_at=_ANNOUNCED_AT,
                updated_at=_ANNOUNCED_AT,
            )
        )
        session.add(
            RawApiResponseRow(
                id=raw_id,
                source="DART",
                operation="corporate_actions",
                endpoint="/test",
                request_fingerprint=f"test:{raw_id}",
                received_at=_ANNOUNCED_AT,
                payload_json="{}",
            )
        )
    return instrument_id, raw_id


async def _seed_bars(
    sessions: Sessions,
    instrument_id: UUID,
    raw_id: UUID,
    *,
    pending_date: date | None = None,
) -> None:
    closes = dict(
        zip(
            _OPEN_DATES,
            (Decimal(1000), Decimal(1010), Decimal(1020), Decimal(1030), Decimal(1040)),
            strict=True,
        )
    )
    async with sessions.begin() as session:
        for day, close in closes.items():
            session.add(_bar_row((instrument_id, raw_id), day, close, pending=day == pending_date))


def _bar_row(
    ids: tuple[UUID, UUID],
    day: date,
    close: Decimal,
    *,
    pending: bool = False,
    version: int = 1,
) -> MarketBarRow:
    instrument_id, raw_id = ids
    return MarketBarRow(
        id=uuid4(),
        instrument_id=instrument_id,
        interval="1d",
        trading_date=day,
        open_price=close - Decimal(10),
        high_price=close + Decimal(20),
        low_price=close - Decimal(20),
        close_price=close,
        volume=100,
        trading_value=Decimal(1_000_000),
        adjusted=False,
        correction_code=None,
        split_ratio=None,
        source="KIS",
        received_at=_ANNOUNCED_AT,
        finality="pending" if pending else "confirmed",
        confirmed_at=None if pending else _ANNOUNCED_AT,
        version=version,
        valid_from=_ANNOUNCED_AT,
        superseded_at=None,
        raw_response_id=raw_id,
    )


async def _correct_bar(
    sessions: Sessions,
    instrument_id: UUID,
    raw_id: UUID,
    day: date,
) -> None:
    async with sessions.begin() as session:
        current = await session.scalar(
            select(MarketBarRow).where(
                MarketBarRow.instrument_id == instrument_id,
                MarketBarRow.trading_date == day,
                MarketBarRow.superseded_at.is_(None),
            )
        )
        assert current is not None
        current.superseded_at = _CORRECTED_AT
        corrected = _bar_row(
            (instrument_id, raw_id),
            day,
            current.close_price + Decimal(5),
            version=current.version + 1,
        )
        session.add(corrected)


def _dividend_action(cash_amount: Decimal) -> CorporateAction:
    return CorporateAction(
        action_type=CorporateActionType.CASH_DIVIDEND,
        lifecycle=CorporateActionLifecycle.ANNOUNCED,
        quality=CorporateActionQuality.VERIFIED,
        announced_at=None,
        announcement_date=_ANNOUNCED_AT.date(),
        time_precision=TimePrecision.DATE,
        ex_date=date(2026, 9, 24),
        effective_date=None,
        record_date=date(2026, 9, 25),
        payment_date=None,
        share_multiplier=None,
        cash_amount=cash_amount,
        currency="KRW",
        subscription_price=None,
        related_instrument_id=None,
        source="DART",
        source_event_id="test-dividend-1",
        source_reference="https://example.test/dividend",
        available_at=_ANNOUNCED_AT,
        received_at=_ANNOUNCED_AT,
    )


async def _seed_dividend(
    sessions: Sessions,
    instrument_id: UUID,
    raw_id: UUID,
    *,
    cash_amount: Decimal,
) -> CorporateAction:
    action = _dividend_action(cash_amount)
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
    return action


async def _seed_correction(
    sessions: Sessions,
    instrument_id: UUID,
    raw_id: UUID,
    original: CorporateAction,
    cash_amount: Decimal,
) -> None:
    corrected = replace(
        original,
        cash_amount=cash_amount,
        available_at=_CORRECTED_AT,
        received_at=_CORRECTED_AT,
    )
    async with sessions.begin() as session:
        await save_corporate_action(
            session,
            CorporateActionEvidence(
                action=corrected,
                action_key=uuid4(),
                instrument_id=instrument_id,
                raw_response_id=raw_id,
            ),
        )


async def _sync_row(sessions: Sessions) -> SyncStatusRow | None:
    async with sessions() as session:
        return await session.scalar(
            select(SyncStatusRow).where(
                SyncStatusRow.source == "INTERNAL",
                SyncStatusRow.operation == "adjusted_prices",
                SyncStatusRow.symbol == _SYMBOL,
            )
        )
