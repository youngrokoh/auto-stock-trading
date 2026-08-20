from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import UUID, uuid4

import anyio
import pytest

from auto_stock_trading.application.trading.notifications import (
    FillNotificationListener,
)
from auto_stock_trading.application.trading.submission import TrackedOrder
from auto_stock_trading.domain.orders.fills import ReconcileProblem
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide, OrderState
from auto_stock_trading.domain.orders.records import AutomationRecord

if TYPE_CHECKING:
    from auto_stock_trading.application.trading.planning import AutomationTransition
    from auto_stock_trading.domain.orders.records import FillNotificationRecord

_NOW: Final = datetime(2026, 8, 19, 4, 15, tzinfo=UTC)
_ENVIRONMENT: Final = "paper"
_ACCOUNT: Final = "abcdef123456"
_TRANSACTION_ID: Final = "H0STCNI9"
_ORDER_ID: Final = UUID("11111111-1111-1111-1111-111111111111")
_FIELDS: Final[tuple[str, ...]] = (
    "CUSTOMER-ID",
    "1234567890",
    "0000012345",
    "0000000000",
    "02",
    "0",
    "00",
    "0",
    "005930",
    "2",
    "250000",
    "101530",
    "0",
    "2",
    "2",
    "91252",
    "4",
    "홍길동",
    "삼성전자",
    "0",
    "00000000",
    "삼성전자",
    "250000",
)


def _payload(**overrides: str) -> str:
    fields: list[str] = list(_FIELDS)
    positions = {"broker_order_id": 2, "quantity": 9, "rejected": 12, "kind": 13, "symbol": 8}
    for name, value in overrides.items():
        fields[positions[name]] = value
    return "^".join(fields)


def _order(
    *,
    quantity: int = 4,
    filled_quantity: int = 0,
    state: OrderState = OrderState.SUBMITTED,
) -> TrackedOrder:
    return TrackedOrder(
        order_id=_ORDER_ID,
        plan_id=uuid4(),
        client_order_id="fixture-client-order-id",
        symbol="005930",
        side=OrderSide.BUY,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=None,
        limit_price=Decimal(250000),
        state=state,
        broker_order_id="0000012345",
        broker_org_no="91252",
    )


@final
@dataclass
class FakeOrders:
    state: AutomationState = AutomationState.RUNNING
    open_orders_result: tuple[TrackedOrder, ...] = ()
    transitions: list[AutomationTransition] = field(default_factory=list)
    problems: list[tuple[str, ReconcileProblem]] = field(default_factory=list)

    async def automation_record(self, environment: str) -> AutomationRecord | None:
        return AutomationRecord(
            environment=environment,
            state=self.state,
            reason_code=None,
            trading_date=_NOW.date(),
            changed_at=_NOW,
        )

    async def transition_automation(self, transition: AutomationTransition) -> AutomationRecord:
        self.transitions.append(transition)
        self.state = transition.requested
        return AutomationRecord(
            environment=transition.environment,
            state=transition.requested,
            reason_code=transition.reason_code,
            trading_date=transition.trading_date,
            changed_at=transition.occurred_at,
        )

    async def open_orders(
        self,
        environment: str,
        trading_date: object,
    ) -> tuple[TrackedOrder, ...]:
        assert environment == _ENVIRONMENT
        assert trading_date is not None
        return self.open_orders_result

    async def record_reconcile_problem(
        self,
        environment: str,
        broker_order_id: str,
        problem: ReconcileProblem,
        occurred_at: datetime,
    ) -> None:
        assert environment == _ENVIRONMENT
        assert occurred_at is not None
        self.problems.append((broker_order_id, problem))


@final
@dataclass
class FakeNotifications:
    order: TrackedOrder | None = None
    # 증권사는 HTTP 응답보다 먼저 통보를 밀어줄 수 있다. 그 사이 조회는 아직 주문을 못 본다.
    lookups_until_visible: int = 0
    lookups: int = 0
    records: list[FillNotificationRecord] = field(default_factory=list)
    sessions: list[tuple[str, UUID]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    closed_before_start: int = 0
    close_reasons: list[str] = field(default_factory=list)

    async def order_by_broker_order_id(
        self,
        environment: str,
        broker_order_id: str,
    ) -> TrackedOrder | None:
        assert environment == _ENVIRONMENT
        self.lookups += 1
        if self.lookups <= self.lookups_until_visible:
            return None
        if self.order is None or self.order.broker_order_id != broker_order_id:
            return None
        return self.order

    async def record_notification(self, record: FillNotificationRecord) -> None:
        self.records.append(record)
        if self.order is not None and record.state is not None:
            self.order = replace(
                self.order,
                state=record.state,
                filled_quantity=record.filled_quantity or self.order.filled_quantity,
            )

    async def start_session(self, environment: str, transaction_id: str, at: datetime) -> UUID:
        assert environment == _ENVIRONMENT
        assert at is not None
        session_id = uuid4()
        self.sessions.append((transaction_id, session_id))
        return session_id

    async def close_open_sessions(self, environment: str, reason: str, at: datetime) -> int:
        assert environment == _ENVIRONMENT
        assert at is not None
        self.close_reasons.append(reason)
        self.closed_before_start += 1
        return self.closed_before_start

    async def heartbeat(self, session_id: UUID, at: datetime) -> None:
        assert at is not None
        self.events.append(f"heartbeat:{session_id}")

    async def end_session(self, session_id: UUID, reason: str, at: datetime) -> None:
        assert at is not None
        self.events.append(f"end:{session_id}:{reason}")

    async def record_listener_event(
        self,
        environment: str,
        reason_code: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        assert environment == _ENVIRONMENT
        assert occurred_at is not None
        self.events.append(f"event:{reason_code}:{detail}")


def _listener(
    orders: FakeOrders,
    notifications: FakeNotifications,
) -> FillNotificationListener:
    return FillNotificationListener(
        orders=orders,
        notifications=notifications,
        environment=_ENVIRONMENT,
        account_reference=_ACCOUNT,
        unmatched_delay_seconds=0.0,
    )


@pytest.mark.parametrize(
    "state",
    [
        AutomationState.RUNNING,
        AutomationState.ARMED,
        AutomationState.PAUSED,
        AutomationState.EMERGENCY_STOP,
    ],
)
def test_the_listener_start_returns_automation_to_disabled(state: AutomationState) -> None:
    """정책 §6: 프로세스 시작 시 자동매매는 항상 DISABLED로 돌아간다."""

    async def run() -> None:
        orders = FakeOrders(state=state)

        result = await _listener(orders, FakeNotifications()).reset_on_start(_NOW)

        assert result is AutomationState.DISABLED
        assert [transition.requested for transition in orders.transitions] == [
            AutomationState.DISABLED
        ]
        assert orders.transitions[0].reason_code == "PROCESS_START"

    anyio.run(run)


def test_a_listener_start_with_automation_already_disabled_changes_nothing() -> None:
    async def run() -> None:
        orders = FakeOrders(state=AutomationState.DISABLED)

        result = await _listener(orders, FakeNotifications()).reset_on_start(_NOW)

        assert result is AutomationState.DISABLED
        assert orders.transitions == []

    anyio.run(run)


def test_a_notification_that_arrives_before_our_commit_is_not_a_mismatch() -> None:
    """증권사는 HTTP 응답 전에 통보를 밀어준다. 아직 커밋되지 않은 우리 주문은 불일치가 아니다."""

    async def run() -> None:
        orders = FakeOrders()
        notifications = FakeNotifications(order=_order(), lookups_until_visible=2)

        result = await _listener(orders, notifications).handle(_payload(), _NOW)

        assert not result.blocked
        assert result.outcomes[0].problem is None
        assert result.outcomes[0].state is OrderState.PARTIALLY_FILLED
        assert orders.problems == []
        assert orders.transitions == []

    anyio.run(run)


def test_an_order_that_never_appears_is_still_a_mismatch() -> None:
    async def run() -> None:
        orders = FakeOrders()
        notifications = FakeNotifications(order=None)

        result = await _listener(orders, notifications).handle(_payload(), _NOW)

        assert result.blocked
        assert result.outcomes[0].problem is ReconcileProblem.UNKNOWN_BROKER_ORDER
        assert notifications.lookups > 1

    anyio.run(run)


def test_execution_notification_confirms_the_order_and_is_stored() -> None:
    async def run() -> None:
        orders = FakeOrders()
        notifications = FakeNotifications(order=_order())
        result = await _listener(orders, notifications).handle(_payload(), _NOW)

        assert not result.blocked
        assert [outcome.state for outcome in result.outcomes] == [OrderState.PARTIALLY_FILLED]
        assert len(notifications.records) == 1
        record = notifications.records[0]
        assert record.order_id == _ORDER_ID
        assert record.state is OrderState.PARTIALLY_FILLED
        assert record.filled_quantity == 2
        assert record.average_fill_price == Decimal(250000)
        assert record.problem is None
        assert orders.transitions == []

    anyio.run(run)


def test_stored_notification_never_carries_personal_fields() -> None:
    async def run() -> None:
        notifications = FakeNotifications(order=_order())
        _ = await _listener(FakeOrders(), notifications).handle(_payload(), _NOW)

        payload = notifications.records[0].masked_payload
        assert "1234567890" not in payload
        assert "홍길동" not in payload
        assert "CUSTOMER-ID" not in payload
        assert payload.startswith("***^***^")

    anyio.run(run)


def test_two_notifications_in_one_frame_are_applied_in_order() -> None:
    async def run() -> None:
        notifications = FakeNotifications(order=_order())
        payload = "^".join((_payload(quantity="1"), _payload(quantity="3")))

        result = await _listener(FakeOrders(), notifications).handle(payload, _NOW)

        assert [outcome.state for outcome in result.outcomes] == [
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
        ]
        assert [record.filled_quantity for record in notifications.records] == [1, 4]

    anyio.run(run)


def test_unknown_broker_order_blocks_and_pauses_automation() -> None:
    async def run() -> None:
        orders = FakeOrders()
        notifications = FakeNotifications(order=None)

        result = await _listener(orders, notifications).handle(_payload(), _NOW)

        assert result.blocked
        assert result.outcomes[0].problem is ReconcileProblem.UNKNOWN_BROKER_ORDER
        assert orders.problems == [("0000012345", ReconcileProblem.UNKNOWN_BROKER_ORDER)]
        assert [transition.requested for transition in orders.transitions] == [
            AutomationState.PAUSED
        ]
        assert orders.transitions[0].reason_code == "ACCOUNT_NOT_RECONCILED"
        assert notifications.records[0].order_id is None
        assert notifications.records[0].state is None

    anyio.run(run)


def test_problem_is_recorded_without_a_transition_when_automation_cannot_pause() -> None:
    async def run() -> None:
        orders = FakeOrders(state=AutomationState.DISABLED)
        notifications = FakeNotifications(order=None)

        result = await _listener(orders, notifications).handle(_payload(), _NOW)

        assert result.blocked
        assert orders.problems
        assert orders.transitions == []

    anyio.run(run)


def test_symbol_mismatch_is_recorded_and_does_not_change_the_order() -> None:
    async def run() -> None:
        orders = FakeOrders()
        notifications = FakeNotifications(order=_order())

        result = await _listener(orders, notifications).handle(_payload(symbol="069500"), _NOW)

        assert result.blocked
        assert result.outcomes[0].problem is ReconcileProblem.SYMBOL_MISMATCH
        assert notifications.records[0].state is None
        assert orders.problems == [("0000012345", ReconcileProblem.SYMBOL_MISMATCH)]

    anyio.run(run)


def test_unreadable_frame_is_recorded_as_unparsable_and_blocks() -> None:
    async def run() -> None:
        orders = FakeOrders()
        notifications = FakeNotifications(order=_order())

        result = await _listener(orders, notifications).handle("not^a^frame", _NOW)

        assert result.blocked
        assert result.outcomes == ()
        assert orders.problems == [("", ReconcileProblem.NOTIFICATION_UNPARSABLE)]
        assert notifications.records == []
        assert [transition.requested for transition in orders.transitions] == [
            AutomationState.PAUSED
        ]

    anyio.run(run)


def test_rejection_that_the_state_graph_forbids_becomes_a_reconcile_problem() -> None:
    async def run() -> None:
        orders = FakeOrders()
        notifications = FakeNotifications(
            order=_order(filled_quantity=2, state=OrderState.PARTIALLY_FILLED)
        )

        result = await _listener(orders, notifications).handle(
            _payload(rejected="1", kind="1", quantity="0"),
            _NOW,
        )

        assert result.blocked
        assert result.outcomes[0].problem is ReconcileProblem.TERMINAL_STATE_CHANGED
        assert notifications.records[0].state is None

    anyio.run(run)


def test_attach_closes_previous_sessions_and_starts_a_new_one() -> None:
    async def run() -> None:
        orders = FakeOrders()
        notifications = FakeNotifications()

        result = await _listener(orders, notifications).attach(_TRANSACTION_ID, _NOW)

        assert not result.blocked
        assert notifications.closed_before_start == 1
        assert notifications.close_reasons == ["SUPERSEDED"]
        assert notifications.sessions[0][0] == _TRANSACTION_ID
        assert result.session_id == notifications.sessions[0][1]
        assert any(event.startswith("event:LISTENER_ATTACHED") for event in notifications.events)

    anyio.run(run)


def test_attach_with_open_orders_blocks_because_notifications_may_be_missing() -> None:
    async def run() -> None:
        orders = FakeOrders(open_orders_result=(_order(),))
        notifications = FakeNotifications()

        result = await _listener(orders, notifications).attach(_TRANSACTION_ID, _NOW)

        assert result.blocked
        assert orders.problems == [("0000012345", ReconcileProblem.NOTIFICATION_GAP)]
        assert [transition.requested for transition in orders.transitions] == [
            AutomationState.PAUSED
        ]

    anyio.run(run)


def test_heartbeat_and_detach_update_the_session() -> None:
    async def run() -> None:
        notifications = FakeNotifications()
        listener = _listener(FakeOrders(), notifications)
        attached = await listener.attach(_TRANSACTION_ID, _NOW)

        await listener.heartbeat(attached.session_id, _NOW)
        await listener.detach(attached.session_id, "CONNECTION_CLOSED", _NOW)

        assert f"heartbeat:{attached.session_id}" in notifications.events
        assert f"end:{attached.session_id}:CONNECTION_CLOSED" in notifications.events
        assert any(event.startswith("event:LISTENER_DETACHED") for event in notifications.events)

    anyio.run(run)
