"""주문 제출·체결 동기화·취소 유스케이스. 사람이 실행할 때만 증권사 쓰기 API를 호출한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol
from zoneinfo import ZoneInfo

from auto_stock_trading.adapters.brokers.kis_orders import CancelRequest, OrderSubmission
from auto_stock_trading.application.trading.planning import AutomationTransition
from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarVerificationState,
    MarketSessionStatus,
    MarketSessionType,
    calendar_session_status,
    calendar_verification_state,
)
from auto_stock_trading.domain.orders.fills import (
    OrderSnapshot,
    ReconcileProblem,
    synchronize,
)
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide, OrderState
from auto_stock_trading.domain.risk.limits import (
    PAPER_RISK_LIMITS,
    BlockCode,
    within_order_window,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.adapters.brokers.kis_orders import (
        BrokerAcknowledgement,
        DailyFillsObservation,
    )
    from auto_stock_trading.domain.market_data.calendar import MarketCalendarRecord
    from auto_stock_trading.domain.market_data.models import RawBrokerResponse
    from auto_stock_trading.domain.orders.records import AutomationRecord
    from auto_stock_trading.domain.risk.limits import RiskLimits

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_COUNTRY: Final = "KR"
_EXCHANGE: Final = "XKRX"
_CANCEL_REQUESTED: Final = "cancel_requested"
_CANCEL_FAILED: Final = "cancel_failed"
_SUBMIT_FAILURE: Final = "order_submit"
_FILLS_FAILURE: Final = "order_fills"
_CANCEL_FAILURE: Final = "order_cancel"


@dataclass(frozen=True, slots=True)
class TrackedOrder:
    """제출·동기화 대상 주문의 내부 현재 상태."""

    order_id: UUID
    plan_id: UUID
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    filled_quantity: int
    average_fill_price: Decimal | None
    limit_price: Decimal | None
    state: OrderState
    broker_order_id: str | None
    broker_org_no: str | None


@dataclass(frozen=True, slots=True)
class SubmissionInput:
    environment: str
    plan_id: UUID | None


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    block_code: str | None
    submitted: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class SyncSummary:
    updated: tuple[tuple[str, OrderState], ...]
    problems: tuple[tuple[str, ReconcileProblem], ...]
    paused: bool


@dataclass(frozen=True, slots=True)
class CancelSummary:
    requested: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


class SubmissionCalendar(Protocol):
    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None: ...


class BrokerGateway(Protocol):
    async def submit(self, submission: OrderSubmission) -> BrokerAcknowledgement: ...

    async def cancel(self, request: CancelRequest) -> BrokerAcknowledgement: ...

    async def fetch_daily_fills(self, trading_date: date) -> DailyFillsObservation: ...


class SubmissionStore(Protocol):
    async def automation_record(self, environment: str) -> AutomationRecord | None: ...

    async def pending_orders(
        self,
        environment: str,
        trading_date: date,
        plan_id: UUID | None,
    ) -> tuple[TrackedOrder, ...]: ...

    async def open_orders(
        self,
        environment: str,
        trading_date: date,
    ) -> tuple[TrackedOrder, ...]: ...

    async def record_submission(
        self,
        order_id: UUID,
        acknowledgement: BrokerAcknowledgement,
        submitted_at: datetime,
    ) -> None: ...

    async def record_rejection(
        self,
        order_id: UUID,
        acknowledgement: BrokerAcknowledgement,
        occurred_at: datetime,
    ) -> None: ...

    async def apply_fill(
        self,
        order_id: UUID,
        state: OrderState,
        filled_quantity: int,
        average_fill_price: Decimal | None,
        occurred_at: datetime,
    ) -> None: ...

    async def record_order_event(
        self,
        order_id: UUID,
        event_type: str,
        detail: str | None,
        occurred_at: datetime,
    ) -> None: ...

    async def record_reconcile_problem(
        self,
        environment: str,
        broker_order_id: str,
        problem: ReconcileProblem,
        occurred_at: datetime,
    ) -> None: ...

    async def transition_automation(
        self,
        transition: AutomationTransition,
    ) -> AutomationRecord: ...

    async def record_api_failure(
        self,
        environment: str,
        detail: str,
        occurred_at: datetime,
    ) -> None: ...

    async def save_broker_response(self, raw: RawBrokerResponse) -> None: ...


def _session_key(trading_date: date) -> CalendarSessionKey:
    return CalendarSessionKey(_COUNTRY, _EXCHANGE, trading_date, MarketSessionType.REGULAR)


def _snapshot(order: TrackedOrder) -> OrderSnapshot:
    return OrderSnapshot(
        client_order_id=order.client_order_id,
        broker_order_id=order.broker_order_id,
        symbol=order.symbol,
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        average_fill_price=order.average_fill_price,
        state=order.state,
    )


def _submission(order: TrackedOrder) -> OrderSubmission | None:
    if order.limit_price is None or order.quantity <= 0:
        return None
    return OrderSubmission(
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        limit_price=order.limit_price,
    )


@dataclass(frozen=True, slots=True)
class OrderSubmitter:
    calendar: SubmissionCalendar
    broker: BrokerGateway
    store: SubmissionStore
    limits: RiskLimits = PAPER_RISK_LIMITS

    async def submit(self, request: SubmissionInput, now: datetime) -> SubmissionResult:
        """계획된 주문만 제출한다. 차단 상태에서는 증권사를 호출하지 않는다."""
        trading_date = now.astimezone(_SEOUL).date()
        block_code = await self._block_code(request.environment, trading_date, now)
        if block_code is not None:
            return SubmissionResult(block_code=block_code, submitted=(), rejected=())
        orders = await self.store.pending_orders(
            request.environment,
            trading_date,
            request.plan_id,
        )
        submitted: list[str] = []
        rejected: list[tuple[str, str]] = []
        for order in orders:
            if order.state is not OrderState.PLANNED:
                continue
            submission = _submission(order)
            if submission is None:
                continue
            acknowledgement = await self._submit_one(request.environment, submission, now)
            if acknowledgement.accepted:
                await self.store.record_submission(order.order_id, acknowledgement, now)
                submitted.append(order.client_order_id)
            else:
                await self.store.record_rejection(order.order_id, acknowledgement, now)
                rejected.append((order.client_order_id, acknowledgement.message_code))
        return SubmissionResult(
            block_code=None,
            submitted=tuple(submitted),
            rejected=tuple(rejected),
        )

    async def synchronize(self, environment: str, now: datetime) -> SyncSummary:
        """증권사 일별주문체결을 근거로 상태를 확정한다. 조회는 차단 상태에서도 수행한다."""
        trading_date = now.astimezone(_SEOUL).date()
        observation = await self._fills(environment, trading_date, now)
        await self.store.save_broker_response(observation.raw)
        orders = await self.store.open_orders(environment, trading_date)
        by_client_order_id = {order.client_order_id: order for order in orders}
        result = synchronize(tuple(_snapshot(order) for order in orders), observation.fills)
        updated: list[tuple[str, OrderState]] = []
        for outcome in result.outcomes:
            if not outcome.changed:
                continue
            order = by_client_order_id[outcome.client_order_id]
            await self.store.apply_fill(
                order.order_id,
                outcome.state,
                outcome.filled_quantity,
                outcome.average_fill_price,
                now,
            )
            updated.append((outcome.client_order_id, outcome.state))
        for broker_order_id, problem in result.problems:
            await self.store.record_reconcile_problem(environment, broker_order_id, problem, now)
        paused = False
        if result.problems:
            _ = await self.store.transition_automation(
                AutomationTransition(
                    environment=environment,
                    requested=AutomationState.PAUSED,
                    reason_code=BlockCode.ACCOUNT_NOT_RECONCILED.value,
                    occurred_at=now,
                    trading_date=trading_date,
                )
            )
            paused = True
        return SyncSummary(
            updated=tuple(updated),
            problems=result.problems,
            paused=paused,
        )

    async def cancel_open_orders(
        self,
        environment: str,
        now: datetime,
        reason_code: str,
    ) -> CancelSummary:
        """미체결 주문 취소를 시도한다. 보유 종목은 청산하지 않는다."""
        trading_date = now.astimezone(_SEOUL).date()
        orders = await self.store.open_orders(environment, trading_date)
        requested: list[str] = []
        failed: list[tuple[str, str]] = []
        for order in orders:
            if order.broker_order_id is None or order.broker_org_no is None:
                continue
            remaining = order.quantity - order.filled_quantity
            if remaining <= 0:
                continue
            acknowledgement = await self._cancel_one(
                environment,
                CancelRequest(
                    broker_org_no=order.broker_org_no,
                    broker_order_id=order.broker_order_id,
                    quantity=remaining,
                ),
                now,
            )
            await self.store.save_broker_response(acknowledgement.raw)
            if acknowledgement.accepted:
                await self.store.record_order_event(
                    order.order_id,
                    _CANCEL_REQUESTED,
                    reason_code,
                    now,
                )
                requested.append(order.client_order_id)
            else:
                await self.store.record_order_event(
                    order.order_id,
                    _CANCEL_FAILED,
                    acknowledgement.message_code,
                    now,
                )
                failed.append((order.client_order_id, acknowledgement.message_code))
        return CancelSummary(requested=tuple(requested), failed=tuple(failed))

    async def _block_code(
        self,
        environment: str,
        trading_date: date,
        now: datetime,
    ) -> str | None:
        automation = await self.store.automation_record(environment)
        if automation is None or automation.state is not AutomationState.RUNNING:
            return BlockCode.AUTOMATION_NOT_RUNNING.value
        if not await self._is_trading_day(trading_date):
            return BlockCode.MARKET_CLOSED.value
        if not within_order_window(now, self.limits):
            return BlockCode.MARKET_CLOSED.value
        return None

    async def _is_trading_day(self, trading_date: date) -> bool:
        record = await self.calendar.session(_session_key(trading_date))
        if record is None:
            return False
        if calendar_verification_state(record.verification) is CalendarVerificationState.CONFLICT:
            return False
        return calendar_session_status(record.session) is not MarketSessionStatus.CLOSED

    async def _submit_one(
        self,
        environment: str,
        submission: OrderSubmission,
        now: datetime,
    ) -> BrokerAcknowledgement:
        try:
            return await self.broker.submit(submission)
        except Exception as error:
            await self.store.record_api_failure(
                environment,
                f"{_SUBMIT_FAILURE}:{type(error).__name__}",
                now,
            )
            raise

    async def _cancel_one(
        self,
        environment: str,
        request: CancelRequest,
        now: datetime,
    ) -> BrokerAcknowledgement:
        try:
            return await self.broker.cancel(request)
        except Exception as error:
            await self.store.record_api_failure(
                environment,
                f"{_CANCEL_FAILURE}:{type(error).__name__}",
                now,
            )
            raise

    async def _fills(
        self,
        environment: str,
        trading_date: date,
        now: datetime,
    ) -> DailyFillsObservation:
        try:
            return await self.broker.fetch_daily_fills(trading_date)
        except Exception as error:
            await self.store.record_api_failure(
                environment,
                f"{_FILLS_FAILURE}:{type(error).__name__}",
                now,
            )
            raise
