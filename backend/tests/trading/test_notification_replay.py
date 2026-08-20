from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, final
from uuid import UUID, uuid4

import anyio

from auto_stock_trading.application.trading.notifications import (
    NotificationReplay,
    PendingNotification,
    ReplayApplication,
)
from auto_stock_trading.application.trading.submission import TrackedOrder
from auto_stock_trading.domain.orders.models import OrderSide, OrderState

_NOW: Final = datetime(2026, 8, 20, 2, 0, tzinfo=UTC)
_ENVIRONMENT: Final = "paper"
_ORDER_ID: Final = UUID("44444444-4444-4444-4444-444444444444")
_ORIGINAL: Final = "0000017323"
_CANCEL_ORDER_ID: Final = "0000017468"
_FIELDS: Final[tuple[str, ...]] = (
    "***",
    "***",
    _CANCEL_ORDER_ID,
    _ORIGINAL,
    "02",
    "2",
    "00",
    "0",
    "005930",
    "0",
    "0",
    "102544",
    "0",
    "1",
    "2",
    "91252",
    "0",
    "***",
    "1Y",
    "10",
    "",
    "삼성전자",
    "0",
)
_PAYLOAD: Final = "^".join(_FIELDS)


def _order(state: OrderState = OrderState.SUBMITTED) -> TrackedOrder:
    return TrackedOrder(
        order_id=_ORDER_ID,
        plan_id=uuid4(),
        client_order_id="fixture-client-order-id",
        symbol="005930",
        side=OrderSide.BUY,
        quantity=1,
        filled_quantity=0,
        average_fill_price=None,
        limit_price=Decimal(263500),
        state=state,
        broker_order_id=_ORIGINAL,
        broker_org_no="91252",
    )


@final
@dataclass
class FakeReplayStore:
    pending_rows: tuple[PendingNotification, ...] = ()
    order: TrackedOrder | None = None
    applied: list[tuple[UUID, OrderState, int]] = field(default_factory=list)
    resolved: list[UUID] = field(default_factory=list)

    async def pending_notifications(self, environment: str) -> tuple[PendingNotification, ...]:
        assert environment == _ENVIRONMENT
        return self.pending_rows

    async def order_by_broker_order_id(
        self,
        environment: str,
        broker_order_id: str,
    ) -> TrackedOrder | None:
        assert environment == _ENVIRONMENT
        if self.order is None or self.order.broker_order_id != broker_order_id:
            return None
        return self.order

    async def apply_replay(self, application: ReplayApplication) -> None:
        assert application.occurred_at is not None
        price = application.average_fill_price
        assert price is None or price > 0
        self.applied.append((application.order_id, application.state, application.filled_quantity))
        self.resolved.append(application.notification_id)


def _pending(payload: str = _PAYLOAD) -> PendingNotification:
    return PendingNotification(
        notification_id=uuid4(),
        payload=payload,
        received_at=_NOW,
        problem="UNKNOWN_BROKER_ORDER",
    )


def test_a_stored_cancel_notification_is_applied_to_the_original_order() -> None:
    async def run() -> None:
        pending = _pending()
        store = FakeReplayStore(pending_rows=(pending,), order=_order())

        summary = await NotificationReplay(store=store, environment=_ENVIRONMENT).replay(_NOW)

        assert summary.applied == 1
        assert summary.unresolved == 0
        assert store.applied == [(_ORDER_ID, OrderState.CANCELED, 0)]
        assert store.resolved == [pending.notification_id]

    anyio.run(run)


def test_a_notification_whose_order_is_still_missing_stays_unresolved() -> None:
    async def run() -> None:
        store = FakeReplayStore(pending_rows=(_pending(),), order=None)

        summary = await NotificationReplay(store=store, environment=_ENVIRONMENT).replay(_NOW)

        assert summary.applied == 0
        assert summary.unresolved == 1
        assert store.applied == []
        assert store.resolved == []

    anyio.run(run)


def test_an_already_terminal_order_is_not_transitioned_again() -> None:
    async def run() -> None:
        store = FakeReplayStore(
            pending_rows=(_pending(),),
            order=_order(state=OrderState.CANCELED),
        )

        summary = await NotificationReplay(store=store, environment=_ENVIRONMENT).replay(_NOW)

        assert summary.applied == 0
        assert summary.unresolved == 1
        assert store.applied == []

    anyio.run(run)


def test_an_unreadable_stored_payload_is_reported_and_left_alone() -> None:
    async def run() -> None:
        store = FakeReplayStore(pending_rows=(_pending(payload="not^a^frame"),), order=_order())

        summary = await NotificationReplay(store=store, environment=_ENVIRONMENT).replay(_NOW)

        assert summary.applied == 0
        assert summary.unreadable == 1
        assert store.applied == []
        assert store.resolved == []

    anyio.run(run)


def test_an_execution_notification_is_replayed_as_a_fill() -> None:
    async def run() -> None:
        fields: list[str] = list(_FIELDS)
        fields[2] = _ORIGINAL
        fields[3] = ""
        fields[5] = "0"
        fields[9] = "1"
        fields[10] = "263500"
        fields[13] = "2"
        fields[16] = "1"
        store = FakeReplayStore(pending_rows=(_pending(payload="^".join(fields)),), order=_order())

        summary = await NotificationReplay(store=store, environment=_ENVIRONMENT).replay(_NOW)

        assert summary.applied == 1
        assert store.applied == [(_ORDER_ID, OrderState.FILLED, 1)]

    anyio.run(run)


def test_nothing_pending_is_a_no_op() -> None:
    async def run() -> None:
        store = FakeReplayStore()

        summary = await NotificationReplay(store=store, environment=_ENVIRONMENT).replay(_NOW)

        assert summary.applied == 0
        assert summary.unresolved == 0
        assert summary.unreadable == 0

    anyio.run(run)
