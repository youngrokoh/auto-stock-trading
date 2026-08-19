from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import UUID

import anyio

from auto_stock_trading.application.trading.attestation import (
    AttestationInput,
    OrderAttestor,
)
from auto_stock_trading.domain.orders.models import OrderState
from auto_stock_trading.domain.orders.records import AttestationTarget

if TYPE_CHECKING:
    from auto_stock_trading.domain.orders.attestation import AttestationOutcome

_NOW: Final = datetime(2026, 8, 19, 7, 30, tzinfo=UTC)
_SUBMITTED_AT: Final = datetime(2026, 8, 19, 0, 6, tzinfo=UTC)
_SESSION_START: Final = datetime(2026, 8, 19, 2, 42, tzinfo=UTC)
_ENVIRONMENT: Final = "paper"
_ORDER_ID: Final = UUID("33333333-3333-3333-3333-333333333333")
_BROKER_ORDER_ID: Final = "0000008637"
_DEFAULT_PRICE: Final = Decimal(248750)


def _target(
    *,
    quantity: int = 2,
    filled_quantity: int = 0,
    state: OrderState = OrderState.SUBMITTED,
    submitted_at: datetime | None = _SUBMITTED_AT,
) -> AttestationTarget:
    return AttestationTarget(
        order_id=_ORDER_ID,
        client_order_id="fixture-client-order-id",
        symbol="005930",
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=None,
        state=state,
        submitted_at=submitted_at,
    )


@final
@dataclass
class FakeStore:
    target_order: AttestationTarget | None = None
    earliest_session: datetime | None = _SESSION_START
    applied: list[tuple[UUID, AttestationOutcome]] = field(default_factory=list)

    async def target(self, environment: str, broker_order_id: str) -> AttestationTarget | None:
        assert environment == _ENVIRONMENT
        if self.target_order is None or broker_order_id != _BROKER_ORDER_ID:
            return None
        return self.target_order

    async def earliest_session_start(self, environment: str) -> datetime | None:
        assert environment == _ENVIRONMENT
        return self.earliest_session

    async def apply_attestation(
        self,
        environment: str,
        order_id: UUID,
        outcome: AttestationOutcome,
    ) -> None:
        assert environment == _ENVIRONMENT
        self.applied.append((order_id, outcome))


def _request(
    *,
    state: OrderState = OrderState.FILLED,
    quantity: int = 2,
    price: Decimal | None = _DEFAULT_PRICE,
    operator: str = "yroh1",
    evidence: str = "KIS 잔고화면 2026-08-19 16:10",
) -> AttestationInput:
    return AttestationInput(
        environment=_ENVIRONMENT,
        broker_order_id=_BROKER_ORDER_ID,
        state=state,
        filled_quantity=quantity,
        average_fill_price=price,
        operator=operator,
        evidence=evidence,
    )


def test_an_order_submitted_before_the_first_listener_session_is_attested() -> None:
    async def run() -> None:
        store = FakeStore(target_order=_target())

        result = await OrderAttestor(store=store).attest(_request(), _NOW)

        assert result.applied
        assert result.reason is None
        assert result.state is OrderState.FILLED
        assert result.client_order_id == "fixture-client-order-id"
        (order_id, outcome) = store.applied[0]
        assert order_id == _ORDER_ID
        assert outcome.filled_quantity == 2
        assert outcome.average_fill_price == Decimal(248750)
        assert outcome.operator == "yroh1"
        assert outcome.occurred_at == _NOW

    anyio.run(run)


def test_an_order_submitted_after_a_listener_session_started_is_refused() -> None:
    async def run() -> None:
        store = FakeStore(
            target_order=_target(submitted_at=_SESSION_START + timedelta(seconds=1)),
        )

        result = await OrderAttestor(store=store).attest(_request(), _NOW)

        assert not result.applied
        assert result.reason == "LISTENER_COVERED"
        assert store.applied == []

    anyio.run(run)


def test_an_environment_without_listener_history_cannot_use_this_path() -> None:
    async def run() -> None:
        store = FakeStore(target_order=_target(), earliest_session=None)

        result = await OrderAttestor(store=store).attest(_request(), _NOW)

        assert not result.applied
        assert result.reason == "NO_LISTENER_HISTORY"
        assert store.applied == []

    anyio.run(run)


def test_an_order_without_a_submission_time_is_refused() -> None:
    async def run() -> None:
        store = FakeStore(target_order=_target(submitted_at=None))

        result = await OrderAttestor(store=store).attest(_request(), _NOW)

        assert not result.applied
        assert result.reason == "LISTENER_COVERED"

    anyio.run(run)


def test_an_unknown_broker_order_id_is_refused() -> None:
    async def run() -> None:
        store = FakeStore(target_order=None)

        result = await OrderAttestor(store=store).attest(_request(), _NOW)

        assert not result.applied
        assert result.reason == "UNKNOWN_ORDER"

    anyio.run(run)


def test_domain_rules_are_reported_without_touching_the_store() -> None:
    async def run() -> None:
        store = FakeStore(target_order=_target())

        result = await OrderAttestor(store=store).attest(_request(quantity=3), _NOW)

        assert not result.applied
        assert result.reason == "QUANTITY_EXCEEDS_ORDER"
        assert store.applied == []

    anyio.run(run)


def test_missing_evidence_is_reported_before_any_store_write() -> None:
    async def run() -> None:
        store = FakeStore(target_order=_target())

        result = await OrderAttestor(store=store).attest(_request(evidence=" "), _NOW)

        assert not result.applied
        assert result.reason == "EVIDENCE_REQUIRED"
        assert store.applied == []

    anyio.run(run)
