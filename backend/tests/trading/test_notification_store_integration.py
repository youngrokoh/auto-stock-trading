from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.brokers.kis_orders import BrokerAcknowledgement
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.trading_notification_store import (
    PostgresNotificationStore,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    AutomationStateRow,
    FillNotificationRow,
    NotificationSessionRow,
    OrderEventRow,
    OrderPlanRow,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse
from auto_stock_trading.domain.orders.fills import ReconcileProblem
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    OrderSide,
    OrderState,
    OrderType,
)
from auto_stock_trading.domain.orders.notifications import (
    NotificationKind,
    mask_notification_payload,
    parse_notifications,
)
from auto_stock_trading.domain.orders.records import (
    FillNotificationRecord,
    OrderPlanRecord,
    OrderRecord,
)
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

    type NotificationScenario = Callable[
        [PostgresNotificationStore, PostgresTradingStore, AsyncConnection],
        Awaitable[None],
    ]

_NOW: Final = datetime(2026, 8, 19, 4, 30, tzinfo=UTC)
_TRADING_DATE: Final = date(2026, 8, 19)
_ENVIRONMENT: Final = "paper"
_ACCOUNT: Final = "abcdef123456"
_SYMBOL: Final = "990003"
_BROKER_ORDER_ID: Final = "0000054321"
_TRANSACTION_ID: Final = "H0STCNI9"
_FIELDS: Final = (
    "CUSTOMER-ID",
    "1234567890",
    _BROKER_ORDER_ID,
    "0000000000",
    "02",
    "0",
    "00",
    "0",
    _SYMBOL,
    "2",
    "100000",
    "103015",
    "0",
    "2",
    "2",
    "91252",
    "4",
    "홍길동",
    "테스트종목",
    "0",
    "00000000",
    "테스트종목",
    "100000",
)
_PAYLOAD: Final = "^".join(_FIELDS)


def _plan(order: OrderRecord) -> OrderPlanRecord:
    return OrderPlanRecord(
        plan_id=uuid4(),
        environment=_ENVIRONMENT,
        strategy_name="ma-rsi",
        strategy_version="1",
        parameters_json='{"short_period":5}',
        signal_date=_TRADING_DATE,
        trading_date=_TRADING_DATE,
        account_snapshot_id=None,
        nav_basis=Decimal(100_000_000),
        session_open_nav=Decimal(100_000_000),
        automation_state=AutomationState.RUNNING,
        status="created",
        block_code=None,
        planned_at=_NOW,
        orders=(order,),
    )


def _order_record() -> OrderRecord:
    return OrderRecord(
        client_order_id=uuid4().hex[:32],
        sequence=1,
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=4,
        limit_price=Decimal(100_000),
        reference_price=Decimal(100_000),
        reference_source="KIS",
        reference_received_at=_NOW,
        state=OrderState.PLANNED,
        reject_code=None,
        decisions=(),
    )


async def _submitted_order(
    store: PostgresTradingStore,
    connection: AsyncConnection,
) -> tuple[UUID, str]:
    _ = await _ensure_instrument(connection, _SYMBOL)
    record = _order_record()
    plan = _plan(record)
    await store.save_plan(plan)
    orders = await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, plan.plan_id)
    order = orders[0]
    await store.record_submission(order.order_id, _acknowledgement(), _NOW)
    return order.order_id, record.client_order_id


def _acknowledgement() -> BrokerAcknowledgement:
    return BrokerAcknowledgement(
        accepted=True,
        broker_order_id=_BROKER_ORDER_ID,
        broker_org_no="91252",
        broker_order_time="103010",
        message_code="40600000",
        message="주문 전송 완료 되었습니다.",
        raw=RawBrokerResponse(
            operation=BrokerOperation.ORDER_SUBMIT,
            endpoint="/uapi/domestic-stock/v1/trading/order-cash",
            request_fingerprint=f"order_submit:{_ACCOUNT}:{_SYMBOL}:buy:1",
            received_at=_NOW,
            payload_json='{"rt_cd":"0"}',
        ),
    )


def _record(  # noqa: PLR0913 — 통보 기록 조립기라 필드를 그대로 노출한다
    order_id: UUID | None,
    *,
    state: OrderState | None,
    filled_quantity: int | None,
    quantity: int | None = None,
    problem: ReconcileProblem | None = None,
    payload: str | None = None,
) -> FillNotificationRecord:
    (notification,) = parse_notifications(_PAYLOAD)
    return FillNotificationRecord(
        environment=_ENVIRONMENT,
        account_reference=_ACCOUNT,
        order_id=order_id,
        notification=notification,
        masked_payload=payload if payload is not None else mask_notification_payload(_PAYLOAD),
        problem=problem,
        state=state,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=None if filled_quantity is None else Decimal(100_000),
        received_at=_NOW,
    )


def test_notification_and_order_transition_are_stored_together() -> None:
    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        order_id, _ = await _submitted_order(store, connection)

        await notifications.record_notification(
            _record(order_id, state=OrderState.PARTIALLY_FILLED, filled_quantity=2)
        )

        tracked = await notifications.order_by_broker_order_id(_ENVIRONMENT, _BROKER_ORDER_ID)
        assert tracked is not None
        assert tracked.order_id == order_id
        assert tracked.state is OrderState.PARTIALLY_FILLED
        assert tracked.filled_quantity == 2
        assert tracked.average_fill_price == Decimal(100_000)
        stored = (
            (
                await connection.execute(
                    select(
                        FillNotificationRow.notification_kind,
                        FillNotificationRow.quantity,
                        FillNotificationRow.masked_payload,
                        FillNotificationRow.problem,
                    ).where(FillNotificationRow.order_id == order_id)
                )
            )
            .tuples()
            .one()
        )
        kind, quantity, masked_payload, problem = stored
        assert kind == NotificationKind.EXECUTION.value
        assert quantity == 2
        assert masked_payload.startswith("***^***^")
        assert "1234567890" not in masked_payload
        assert "홍길동" not in masked_payload
        assert problem is None

    anyio.run(_run_scenario, scenario)


def test_a_partial_cancel_notification_reduces_the_stored_quantity_without_a_transition() -> None:
    """ADR-0013 결정 6: 부분 취소는 수량만 줄이고 상태는 유지한다. 이력은 이벤트로 남는다."""

    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        order_id, _ = await _submitted_order(store, connection)

        # 기록의 `quantity`는 취소량이 아니라 축소 후 주문 수량이다(4주 중 1주 취소 → 3주).
        await notifications.record_notification(
            _record(order_id, state=None, quantity=3, filled_quantity=None)
        )

        tracked = await notifications.order_by_broker_order_id(_ENVIRONMENT, _BROKER_ORDER_ID)
        assert tracked is not None
        assert tracked.quantity == 3
        assert tracked.state is OrderState.SUBMITTED
        assert tracked.filled_quantity == 0
        events = (
            (
                await connection.execute(
                    select(
                        OrderEventRow.previous_state,
                        OrderEventRow.state,
                        OrderEventRow.reason_code,
                        OrderEventRow.detail,
                    )
                    .where(OrderEventRow.order_id == order_id)
                    .order_by(OrderEventRow.sequence)
                )
            )
            .tuples()
            .all()
        )
        previous, state, reason, detail = events[-1]
        assert previous == OrderState.SUBMITTED.value
        assert state == OrderState.SUBMITTED.value
        assert reason is not None
        # 감사 기록은 바뀐 값을 보여야 한다. 2026-08-25 장중 실측에서 `102 -> 102`로 남아
        # 변경 전 수량이 사라졌다 — UPDATE 뒤에 읽으면 이미 갱신된 값이 나온다.
        assert detail == "quantity 4 -> 3"

    anyio.run(_run_scenario, scenario)


def test_unmatched_notification_is_stored_without_an_order() -> None:
    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        assert store is not None

        await notifications.record_notification(
            _record(
                None,
                state=None,
                quantity=None,
                filled_quantity=None,
                problem=ReconcileProblem.UNKNOWN_BROKER_ORDER,
            )
        )

        stored_order_id, stored_problem = (
            (
                await connection.execute(
                    select(FillNotificationRow.order_id, FillNotificationRow.problem).where(
                        FillNotificationRow.environment == _ENVIRONMENT
                    )
                )
            )
            .tuples()
            .one()
        )
        assert stored_order_id is None
        assert stored_problem == ReconcileProblem.UNKNOWN_BROKER_ORDER.value

    anyio.run(_run_scenario, scenario)


def test_unmasked_payload_is_rejected_by_the_database() -> None:
    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        assert store is not None
        assert connection is not None

        with pytest.raises(IntegrityError):
            await notifications.record_notification(
                _record(None, state=None, filled_quantity=None, payload=_PAYLOAD)
            )

    anyio.run(_run_scenario, scenario)


def test_sessions_are_attached_heartbeaten_and_ended() -> None:
    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        assert store is not None
        assert connection is not None

        assert not await notifications.attached(_ENVIRONMENT, _NOW)
        session_id = await notifications.start_session(_ENVIRONMENT, _TRANSACTION_ID, _NOW)
        assert await notifications.attached(_ENVIRONMENT, _NOW)

        await notifications.heartbeat(session_id, _NOW + timedelta(seconds=10))
        assert await notifications.attached(_ENVIRONMENT, _NOW + timedelta(seconds=20))

        await notifications.end_session(session_id, "CONNECTION_CLOSED", _NOW)
        assert not await notifications.attached(_ENVIRONMENT, _NOW)

    anyio.run(_run_scenario, scenario)


def test_a_stale_heartbeat_is_not_attached() -> None:
    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        assert store is not None
        assert connection is not None

        _ = await notifications.start_session(_ENVIRONMENT, _TRANSACTION_ID, _NOW)

        assert not await notifications.attached(_ENVIRONMENT, _NOW + timedelta(seconds=31))

    anyio.run(_run_scenario, scenario)


def test_starting_a_session_closes_the_previous_one() -> None:
    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        assert store is not None
        first = await notifications.start_session(_ENVIRONMENT, _TRANSACTION_ID, _NOW)

        closed = await notifications.close_open_sessions(_ENVIRONMENT, "RESTARTED", _NOW)
        second = await notifications.start_session(_ENVIRONMENT, _TRANSACTION_ID, _NOW)

        assert closed == 1
        assert first != second
        states = (
            (
                await connection.execute(
                    select(NotificationSessionRow.state, func.count())
                    .where(NotificationSessionRow.environment == _ENVIRONMENT)
                    .group_by(NotificationSessionRow.state)
                )
            )
            .tuples()
            .all()
        )
        assert dict(states) == {"connected": 1, "closed": 1}

    anyio.run(_run_scenario, scenario)


def test_two_connected_sessions_are_rejected_by_the_database() -> None:
    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        assert store is not None
        assert connection is not None
        _ = await notifications.start_session(_ENVIRONMENT, _TRANSACTION_ID, _NOW)

        with pytest.raises(IntegrityError):
            _ = await notifications.start_session(_ENVIRONMENT, _TRANSACTION_ID, _NOW)

    anyio.run(_run_scenario, scenario)


def test_listener_events_are_recorded_as_automation_events() -> None:
    async def scenario(
        notifications: PostgresNotificationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        assert store is not None

        await notifications.record_listener_event(
            _ENVIRONMENT,
            "LISTENER_ATTACHED",
            _TRANSACTION_ID,
            _NOW,
        )

        event_type, reason_code, detail = (
            (
                await connection.execute(
                    select(
                        AutomationEventRow.event_type,
                        AutomationEventRow.reason_code,
                        AutomationEventRow.detail,
                    ).where(AutomationEventRow.environment == _ENVIRONMENT)
                )
            )
            .tuples()
            .one()
        )
        assert event_type == "listener_state"
        assert reason_code == "LISTENER_ATTACHED"
        assert detail == _TRANSACTION_ID

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: NotificationScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await _purge_environment(connection)
        notifications = PostgresNotificationStore.from_connection(connection)
        store = PostgresTradingStore.from_connection(connection)
        try:
            await scenario(notifications, store, connection)
        finally:
            await notifications.close()
            await store.close()
            await transaction.rollback()
    await engine.dispose()


async def _purge_environment(connection: AsyncConnection) -> None:
    """이 트랜잭션 안에서만 환경 데이터를 비운다. 실제 실행 기록은 롤백으로 복원된다."""
    for table in (
        FillNotificationRow,
        NotificationSessionRow,
        OrderPlanRow,
        AutomationEventRow,
        AutomationStateRow,
    ):
        _ = await connection.execute(delete(table).where(table.environment == _ENVIRONMENT))


async def _ensure_instrument(connection: AsyncConnection, symbol: str) -> UUID:
    existing = await connection.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == symbol).limit(1)
    )
    if existing is not None:
        return existing
    instrument_id = uuid4()
    _ = await connection.execute(
        insert(InstrumentRow).values(
            id=instrument_id,
            country="KR",
            exchange="KRX",
            symbol=symbol,
            product_type="stock",
            currency="KRW",
            name="체결통보 통합 테스트 종목",
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
