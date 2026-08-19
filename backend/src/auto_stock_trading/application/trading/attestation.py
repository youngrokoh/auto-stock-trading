"""사람이 확인한 대조 종결 유스케이스(ADR-0010). 증권사 API를 호출하지 않는다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from auto_stock_trading.domain.orders.attestation import (
    AttestationReason,
    AttestationRejection,
    AttestationRequest,
    attest_order,
)
from auto_stock_trading.domain.orders.fills import OrderSnapshot

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.domain.orders.attestation import AttestationOutcome
    from auto_stock_trading.domain.orders.models import OrderState
    from auto_stock_trading.domain.orders.records import AttestationTarget


@dataclass(frozen=True, slots=True)
class AttestationInput:
    environment: str
    broker_order_id: str
    state: OrderState
    filled_quantity: int
    average_fill_price: Decimal | None
    operator: str
    evidence: str


@dataclass(frozen=True, slots=True)
class AttestationResult:
    applied: bool
    reason: str | None
    client_order_id: str | None
    state: OrderState | None


class AttestationStore(Protocol):
    async def target(
        self,
        environment: str,
        broker_order_id: str,
    ) -> AttestationTarget | None: ...

    async def earliest_session_start(self, environment: str) -> datetime | None: ...

    async def apply_attestation(
        self,
        environment: str,
        order_id: UUID,
        outcome: AttestationOutcome,
    ) -> None: ...


def _refused(reason: AttestationReason) -> AttestationResult:
    return AttestationResult(
        applied=False,
        reason=reason.value,
        client_order_id=None,
        state=None,
    )


def _snapshot(target: AttestationTarget, broker_order_id: str) -> OrderSnapshot:
    return OrderSnapshot(
        client_order_id=target.client_order_id,
        broker_order_id=broker_order_id,
        symbol=target.symbol,
        quantity=target.quantity,
        filled_quantity=target.filled_quantity,
        average_fill_price=target.average_fill_price,
        state=target.state,
    )


@dataclass(frozen=True, slots=True)
class OrderAttestor:
    store: AttestationStore

    async def attest(self, request: AttestationInput, now: datetime) -> AttestationResult:
        """리스너 부착 전에 제출된 주문만 사람이 확인한 사실로 종결한다."""
        target = await self.store.target(request.environment, request.broker_order_id)
        if target is None:
            return _refused(AttestationReason.UNKNOWN_ORDER)
        earliest = await self.store.earliest_session_start(request.environment)
        if earliest is None:
            return _refused(AttestationReason.NO_LISTENER_HISTORY)
        submitted_at = target.submitted_at
        if submitted_at is None or submitted_at >= earliest:
            return _refused(AttestationReason.LISTENER_COVERED)
        outcome = attest_order(
            _snapshot(target, request.broker_order_id),
            AttestationRequest(
                state=request.state,
                filled_quantity=request.filled_quantity,
                average_fill_price=request.average_fill_price,
                operator=request.operator,
                evidence=request.evidence,
                occurred_at=now,
            ),
        )
        if isinstance(outcome, AttestationRejection):
            return _refused(outcome.reason)
        await self.store.apply_attestation(request.environment, target.order_id, outcome)
        return AttestationResult(
            applied=True,
            reason=None,
            client_order_id=outcome.client_order_id,
            state=outcome.state,
        )
