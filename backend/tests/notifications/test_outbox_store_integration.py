"""아웃박스 저장소 통합 테스트. 적용된 스키마에서 투영과 유일 제약을 확인한다.

핵심은 두 가지다. anti-join이 **아직 투영되지 않은** 이벤트만 돌려주는가, 그리고 같은 이벤트를 두 번
투영하려 할 때 DB가 막는가.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4

import anyio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.notification_rows import (
    NotificationOutboxRow,
    NotificationWatermarkRow,
)
from auto_stock_trading.adapters.database.notification_store import (
    MAX_DELIVERY_ATTEMPTS,
    PostgresNotificationOutboxStore,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    OrderPlanRow,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.notifications.dispatch import OutboxEntry
from auto_stock_trading.domain.notifications.events import EventSource
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    OrderSide,
    OrderState,
    OrderType,
)
from auto_stock_trading.domain.orders.records import OrderPlanRecord, OrderRecord
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncConnection

    type OutboxScenario = Callable[
        [PostgresNotificationOutboxStore, PostgresTradingStore, AsyncConnection],
        Awaitable[None],
    ]

_NOW: Final = datetime(2026, 8, 24, 4, 30, tzinfo=UTC)
_SINCE: Final = _NOW - timedelta(hours=6)
_TRADING_DATE: Final = date(2026, 8, 24)
_ENVIRONMENT: Final = "paper"
_SYMBOL: Final = "005930"


async def _run_scenario(scenario: OutboxScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await _purge(connection)
        store = PostgresNotificationOutboxStore.from_connection(connection)
        trading = PostgresTradingStore.from_connection(connection)
        try:
            await scenario(store, trading, connection)
        finally:
            await store.close()
            await trading.close()
            await transaction.rollback()
    await engine.dispose()


async def _purge(connection: AsyncConnection) -> None:
    for table in (NotificationOutboxRow, NotificationWatermarkRow, OrderPlanRow):
        _ = await connection.execute(delete(table).where(table.environment == _ENVIRONMENT))
    _ = await connection.execute(
        delete(AutomationEventRow).where(AutomationEventRow.environment == _ENVIRONMENT)
    )


async def _ensure_instrument(connection: AsyncConnection) -> UUID:
    """CI는 갓 마이그레이션한 빈 DB로 돈다. 종목이 있다고 가정하지 않고 직접 만든다."""
    existing = await connection.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == _SYMBOL).limit(1)
    )
    if existing is not None:
        return existing
    instrument_id = uuid4()
    _ = await connection.execute(
        insert(InstrumentRow).values(
            id=instrument_id,
            country="KR",
            exchange="KRX",
            symbol=_SYMBOL,
            product_type="stock",
            currency="KRW",
            name="알림 아웃박스 통합 테스트 종목",
            english_name=None,
            listed_on=None,
            delisted_on=None,
            trading_status="active",
            source="TEST",
            source_as_of=_TRADING_DATE,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    return instrument_id


async def _submitted_order(store: PostgresTradingStore) -> str:
    record = OrderRecord(
        client_order_id=uuid4().hex[:32],
        sequence=1,
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=2,
        limit_price=Decimal(250_000),
        reference_price=Decimal(250_000),
        reference_source="KIS",
        reference_received_at=_NOW,
        state=OrderState.PLANNED,
        reject_code=None,
        decisions=(),
    )
    plan = OrderPlanRecord(
        plan_id=uuid4(),
        environment=_ENVIRONMENT,
        strategy_name="ma-rsi",
        strategy_version="1",
        parameters_json='{"short_period":5}',
        signal_date=_TRADING_DATE,
        trading_date=_TRADING_DATE,
        account_snapshot_id=None,
        nav_basis=Decimal(10_000_000),
        session_open_nav=Decimal(10_000_000),
        automation_state=AutomationState.RUNNING,
        status="created",
        block_code=None,
        planned_at=_NOW,
        orders=(record,),
    )
    await store.save_plan(plan)
    return record.client_order_id


def test_a_new_order_event_is_projected_once_and_then_not_again() -> None:
    async def scenario(
        store: PostgresNotificationOutboxStore,
        trading: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection)
        _ = await _submitted_order(trading)

        first = await store.unprojected_events(_ENVIRONMENT, _SINCE)
        order_events = [c for c in first if c.source is EventSource.ORDER_EVENT]
        assert order_events

        saved = await store.save_outbox(
            tuple(
                OutboxEntry(
                    entry_id=uuid4(),
                    environment=_ENVIRONMENT,
                    source=candidate.source.value,
                    source_id=candidate.source_id,
                    kind="order_state",
                    severity="info",
                    body="본문",
                    state="pending",
                    last_error=None,
                    event_occurred_at=candidate.occurred_at,
                )
                for candidate in order_events
            )
        )
        assert saved == len(order_events)

        # anti-join이므로 이미 투영된 이벤트는 다시 나오지 않는다.
        second = await store.unprojected_events(_ENVIRONMENT, _SINCE)
        assert [c for c in second if c.source is EventSource.ORDER_EVENT] == []

    anyio.run(_run_scenario, scenario)


def test_projecting_the_same_event_twice_is_absorbed_by_the_unique_constraint() -> None:
    async def scenario(
        store: PostgresNotificationOutboxStore,
        trading: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = (trading, connection)
        source_id = uuid4()

        def entry() -> OutboxEntry:
            return OutboxEntry(
                entry_id=uuid4(),
                environment=_ENVIRONMENT,
                source=EventSource.AUTOMATION_EVENT.value,
                source_id=source_id,
                kind="automation_state",
                severity="info",
                body="본문",
                state="pending",
                last_error=None,
                event_occurred_at=_NOW,
            )

        assert await store.save_outbox((entry(),)) == 1
        # 두 번째는 조용히 흡수된다 — 예외가 아니라 0건이다.
        assert await store.save_outbox((entry(),)) == 0

    anyio.run(_run_scenario, scenario)


def test_sending_marks_the_row_and_removes_it_from_pending() -> None:
    async def scenario(
        store: PostgresNotificationOutboxStore,
        trading: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = (trading, connection)
        entry = OutboxEntry(
            entry_id=uuid4(),
            environment=_ENVIRONMENT,
            source=EventSource.AUTOMATION_EVENT.value,
            source_id=uuid4(),
            kind="automation_state",
            severity="warning",
            body="본문",
            state="pending",
            last_error=None,
            event_occurred_at=_NOW,
        )
        _ = await store.save_outbox((entry,))

        pending = await store.pending_entries(_ENVIRONMENT, 10)
        assert [row.entry_id for row in pending] == [entry.entry_id]

        await store.mark_sent(entry.entry_id, _NOW, None)

        assert await store.pending_entries(_ENVIRONMENT, 10) == ()
        counts = await store.counts(_ENVIRONMENT)
        assert counts[0] == 0
        assert counts[2] == 1

    anyio.run(_run_scenario, scenario)


def test_a_failure_keeps_the_row_pending_and_counts_the_attempt() -> None:
    """실패해도 다음 폴이 다시 시도한다. 시도 횟수와 사유가 사실로 남는다."""

    async def scenario(
        store: PostgresNotificationOutboxStore,
        trading: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = trading
        entry = OutboxEntry(
            entry_id=uuid4(),
            environment=_ENVIRONMENT,
            source=EventSource.AUTOMATION_EVENT.value,
            source_id=uuid4(),
            kind="api_failure",
            severity="warning",
            body="본문",
            state="pending",
            last_error=None,
            event_occurred_at=_NOW,
        )
        _ = await store.save_outbox((entry,))

        await store.mark_failed(entry.entry_id, "429 Too Many Requests", _NOW)

        stored = (
            (
                await connection.execute(
                    select(
                        NotificationOutboxRow.state,
                        NotificationOutboxRow.attempts,
                        NotificationOutboxRow.last_error,
                    ).where(NotificationOutboxRow.id == entry.entry_id)
                )
            )
            .tuples()
            .one()
        )
        assert stored == ("pending", 1, "429 Too Many Requests")
        assert len(await store.pending_entries(_ENVIRONMENT, 10)) == 1

    anyio.run(_run_scenario, scenario)


def test_the_watermark_is_written_once_and_kept() -> None:
    """워터마크를 계속 옮기면 프로세스가 멈춰 있던 기간의 이벤트가 사라진다."""

    async def scenario(
        store: PostgresNotificationOutboxStore,
        trading: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = (trading, connection)
        assert await store.projection_watermark(_ENVIRONMENT) is None

        await store.set_projection_watermark(_ENVIRONMENT, _SINCE)
        first = await store.projection_watermark(_ENVIRONMENT)
        assert first == _SINCE

        await store.set_projection_watermark(_ENVIRONMENT, _NOW)
        assert await store.projection_watermark(_ENVIRONMENT) == _SINCE

    anyio.run(_run_scenario, scenario)


def test_a_forbidden_field_row_is_stored_as_failed_and_never_pending() -> None:
    async def scenario(
        store: PostgresNotificationOutboxStore,
        trading: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = (trading, connection)
        entry = OutboxEntry(
            entry_id=uuid4(),
            environment=_ENVIRONMENT,
            source=EventSource.AUTOMATION_EVENT.value,
            source_id=uuid4(),
            kind="api_failure",
            severity="warning",
            body="",
            state="failed",
            last_error="FORBIDDEN_FIELD",
            event_occurred_at=_NOW,
        )
        _ = await store.save_outbox((entry,))

        assert await store.pending_entries(_ENVIRONMENT, 10) == ()
        counts = await store.counts(_ENVIRONMENT)
        assert counts[1] == 1

    anyio.run(_run_scenario, scenario)


def test_repeated_failures_become_failed_after_the_retry_cap() -> None:
    """ADR-0014 결정 8: 상한을 넘으면 `failed`로 남기고 자동 삭제하지 않는다.

    상한이 없으면 도달 불가능한 알림이 영원히 재시도 대상으로 남아 매 폴마다 한도를 쓴다.
    """

    async def scenario(
        store: PostgresNotificationOutboxStore,
        trading: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = trading
        entry = OutboxEntry(
            entry_id=uuid4(),
            environment=_ENVIRONMENT,
            source=EventSource.AUTOMATION_EVENT.value,
            source_id=uuid4(),
            kind="api_failure",
            severity="warning",
            body="본문",
            state="pending",
            last_error=None,
            event_occurred_at=_NOW,
        )
        _ = await store.save_outbox((entry,))

        for _attempt in range(MAX_DELIVERY_ATTEMPTS):
            await store.mark_failed(entry.entry_id, "429 Too Many Requests", _NOW)

        state, attempts = (
            (
                await connection.execute(
                    select(
                        NotificationOutboxRow.state,
                        NotificationOutboxRow.attempts,
                    ).where(NotificationOutboxRow.id == entry.entry_id)
                )
            )
            .tuples()
            .one()
        )
        assert attempts == MAX_DELIVERY_ATTEMPTS
        assert state == "failed"
        # 상한에 닿은 행은 다음 폴의 대상이 아니다.
        assert await store.pending_entries(_ENVIRONMENT, 10) == ()
        # 그러나 사라지지 않는다 — 실패 건수로 남는다.
        assert (await store.counts(_ENVIRONMENT))[1] == 1

    anyio.run(_run_scenario, scenario)
