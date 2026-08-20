"""주문 정정 유스케이스(ADR-0011). 사람이 지정한 주문의 지정가만 바꾼다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Protocol

from auto_stock_trading.adapters.brokers.kis_orders import ReviseRequest
from auto_stock_trading.domain.orders.models import AutomationState, OrderState
from auto_stock_trading.domain.orders.pricing import offset_limit_price
from auto_stock_trading.domain.risk.engine import (
    PlanRequest,
    SignalCandidate,
    evaluate_plan,
)
from auto_stock_trading.domain.risk.limits import (
    PAPER_RISK_LIMITS,
    BlockCode,
    RiskRule,
    within_order_window,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.adapters.brokers.kis_orders import BrokerAcknowledgement
    from auto_stock_trading.application.trading.planning import PlanContext
    from auto_stock_trading.application.trading.submission import TrackedOrder
    from auto_stock_trading.domain.market_data.models import RawBrokerResponse
    from auto_stock_trading.domain.orders.records import AutomationRecord
    from auto_stock_trading.domain.risk.engine import (
        MarketQuote,
        RiskDecision,
        RiskEvaluation,
    )
    from auto_stock_trading.domain.risk.limits import RiskLimits

_OPEN_STATES: Final = frozenset({OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED})
_UNKNOWN_ORDER: Final = "UNKNOWN_ORDER"
_NOT_OPEN: Final = "NOT_OPEN"
_NOTHING_LEFT: Final = "NOTHING_LEFT"
_API_FAILURE: Final = "order_revise"


@dataclass(frozen=True, slots=True)
class RevisionInput:
    environment: str
    broker_order_id: str
    price_offset: Decimal


@dataclass(frozen=True, slots=True)
class RevisionResult:
    applied: bool
    reject_code: str | None
    limit_price: Decimal | None
    decisions: tuple[RiskDecision, ...]


class RevisionContext(Protocol):
    """계획과 같은 수집·정지 경로. `OrderPlanner`가 그대로 만족한다."""

    async def context(
        self,
        environment: str,
        symbols: tuple[str, ...],
        now: datetime,
        exclude_order_id: UUID | None = None,
    ) -> PlanContext: ...

    async def pause(
        self,
        environment: str,
        rule: RiskRule,
        now: datetime,
    ) -> AutomationRecord: ...


class RevisionBroker(Protocol):
    async def revise(self, request: ReviseRequest) -> BrokerAcknowledgement: ...


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    """정정 한 건의 저장 입력. 판정과 전이를 같은 트랜잭션에 넣기 위한 값이다."""

    order_id: UUID
    acknowledgement: BrokerAcknowledgement
    limit_price: Decimal
    attempt: int
    decisions: tuple[RiskDecision, ...]
    occurred_at: datetime


class RevisionStore(Protocol):
    async def open_order(
        self,
        environment: str,
        broker_order_id: str,
    ) -> TrackedOrder | None: ...

    async def next_revision_attempt(self, order_id: UUID) -> int: ...

    async def record_revision(self, record: RevisionRecord) -> None: ...

    async def record_revision_rejection(self, record: RevisionRecord) -> None: ...

    async def save_broker_response(self, raw: RawBrokerResponse) -> None: ...

    async def record_api_failure(
        self,
        environment: str,
        detail: str,
        occurred_at: datetime,
    ) -> None: ...


def _refused(reject_code: str, decisions: tuple[RiskDecision, ...] = ()) -> RevisionResult:
    return RevisionResult(
        applied=False,
        reject_code=reject_code,
        limit_price=None,
        decisions=decisions,
    )


def _quote_for(context: PlanContext, symbol: str) -> MarketQuote | None:
    return next((quote for quote in context.quotes if quote.symbol == symbol), None)


def _evaluation_refusal(
    evaluation: RiskEvaluation,
    symbol: str,
    remaining: int,
    limit_price: Decimal,
) -> RevisionResult | None:
    """계획 엔진 판정을 정정 거절로 옮긴다. 같은 수량·가격을 낼 수 없으면 정정도 못 한다."""
    if evaluation.block_code is not None:
        return _refused(evaluation.block_code)
    planned = next((item for item in evaluation.orders if item.symbol == symbol), None)
    if planned is None:
        return _refused(BlockCode.DATA_STALE.value)
    if planned.reject_code is not None:
        return _refused(planned.reject_code, planned.decisions)
    if planned.quantity < remaining or planned.limit_price != limit_price:
        return _refused(RiskRule.ORDER_AMOUNT.value, planned.decisions)
    return None


@dataclass(frozen=True, slots=True)
class OrderReviser:
    context: RevisionContext
    broker: RevisionBroker
    store: RevisionStore
    limits: RiskLimits = PAPER_RISK_LIMITS

    async def revise(self, request: RevisionInput, now: datetime) -> RevisionResult:
        """대상 주문의 지정가만 바꾼다. 수량과 상태는 그대로 둔다."""
        order = await self.store.open_order(request.environment, request.broker_order_id)
        if order is None:
            return _refused(_UNKNOWN_ORDER)
        if order.state not in _OPEN_STATES or order.broker_org_no is None:
            return _refused(_NOT_OPEN)
        remaining = order.quantity - order.filled_quantity
        if remaining <= 0:
            return _refused(_NOTHING_LEFT)
        if not within_order_window(now, self.limits):
            return _refused(BlockCode.MARKET_CLOSED.value)
        plan_context = await self.context.context(
            request.environment,
            (order.symbol,),
            now,
            order.order_id,
        )
        gate = self._gate(plan_context, now)
        if gate is not None:
            return _refused(gate)
        return await self._checked_revision(request, order, plan_context, now)

    def _gate(self, plan_context: PlanContext, now: datetime) -> str | None:
        if plan_context.automation.state is not AutomationState.RUNNING:
            return BlockCode.AUTOMATION_NOT_RUNNING.value
        if not plan_context.trading_day:
            return BlockCode.MARKET_CLOSED.value
        if not plan_context.account.reconciled:
            return BlockCode.ACCOUNT_NOT_RECONCILED.value
        _ = now
        return None

    async def _checked_revision(
        self,
        request: RevisionInput,
        order: TrackedOrder,
        plan_context: PlanContext,
        now: datetime,
    ) -> RevisionResult:
        quote = _quote_for(plan_context, order.symbol)
        if quote is None or (
            now - quote.received_at > timedelta(seconds=self.limits.quote_max_age_seconds)
        ):
            return _refused(BlockCode.DATA_STALE.value)
        limit_price = offset_limit_price(quote.price, quote.product_type, request.price_offset)
        remaining = order.quantity - order.filled_quantity
        evaluation = evaluate_plan(
            PlanRequest(
                candidates=(SignalCandidate(order.symbol, order.side),),
                account=plan_context.account,
                quotes=plan_context.quotes,
                counters=plan_context.counters,
                automation_state=plan_context.automation.state,
                trading_day=plan_context.trading_day,
                now=now,
                limits=self.limits,
                pending=plan_context.pending,
                price_offset=request.price_offset,
            )
        )
        if evaluation.pause_rule is not None:
            _ = await self.context.pause(request.environment, evaluation.pause_rule, now)
            return _refused(evaluation.pause_rule.value)
        refusal = _evaluation_refusal(evaluation, order.symbol, remaining, limit_price)
        if refusal is not None:
            return refusal
        planned = next(item for item in evaluation.orders if item.symbol == order.symbol)
        return await self._send(request, order, planned.decisions, limit_price, now)

    async def _send(
        self,
        request: RevisionInput,
        order: TrackedOrder,
        decisions: tuple[RiskDecision, ...],
        limit_price: Decimal,
        now: datetime,
    ) -> RevisionResult:
        attempt = await self.store.next_revision_attempt(order.order_id)
        remaining = order.quantity - order.filled_quantity
        broker_org_no = order.broker_org_no or ""
        broker_order_id = order.broker_order_id or ""
        try:
            acknowledgement = await self.broker.revise(
                ReviseRequest(
                    broker_org_no=broker_org_no,
                    broker_order_id=broker_order_id,
                    quantity=remaining,
                    limit_price=limit_price,
                )
            )
        except Exception as error:
            await self.store.record_api_failure(
                request.environment,
                f"{_API_FAILURE}:{type(error).__name__}",
                now,
            )
            raise
        await self.store.save_broker_response(acknowledgement.raw)
        record = RevisionRecord(
            order_id=order.order_id,
            acknowledgement=acknowledgement,
            limit_price=limit_price,
            attempt=attempt,
            decisions=decisions,
            occurred_at=now,
        )
        if not acknowledgement.accepted or acknowledgement.broker_order_id is None:
            await self.store.record_revision_rejection(record)
            return _refused(acknowledgement.message_code, decisions)
        await self.store.record_revision(record)
        return RevisionResult(
            applied=True,
            reject_code=None,
            limit_price=limit_price,
            decisions=decisions,
        )
