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
from auto_stock_trading.domain.orders.recovery import (
    STALE_TRADING_DAY_REASON,
    is_stale_trading_day,
)
from auto_stock_trading.domain.orders.session_close import (
    AggregateVerdict,
    close_session_orders,
    compare_daily_totals,
    session_ended,
)
from auto_stock_trading.domain.risk.limits import (
    PAPER_RISK_LIMITS,
    BlockCode,
    within_order_window,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
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
    from auto_stock_trading.domain.orders.session_close import InternalDailyTotals
    from auto_stock_trading.domain.risk.limits import RiskLimits

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_COUNTRY: Final = "KR"
_EXCHANGE: Final = "XKRX"
_CANCEL_REQUESTED: Final = "cancel_requested"
_CANCEL_FAILED: Final = "cancel_failed"
_PARTIAL_CANCEL_REQUESTED: Final = "partial_cancel_requested"
_PARTIAL_CANCEL_FAILED: Final = "partial_cancel_failed"
_ORDER_NOT_FOUND: Final = "ORDER_NOT_FOUND"
_INVALID_QUANTITY: Final = "INVALID_QUANTITY"
_QUANTITY_EXCEEDS_OUTSTANDING: Final = "QUANTITY_EXCEEDS_OUTSTANDING"
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
    # 계좌 단위 재대조 결과(ADR-0017 결정 3). 조회 성공과 대조 수행은 다른 사건이다.
    verdict: AggregateVerdict = AggregateVerdict.UNAVAILABLE
    # 세션 종료로 종결한 주문. 집계가 일치할 때만 채워진다.
    expired: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CancelSummary:
    requested: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ReductionResult:
    """부분 취소 요청 결과. 수량 반영은 체결통보가 하며 여기서는 요청 사실만 남는다."""

    client_order_id: str
    requested_quantity: int
    accepted: bool
    reason_code: str | None
    cancel_order_id: str | None


class SubmissionCalendar(Protocol):
    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None: ...


class BrokerGateway(Protocol):
    async def submit(self, submission: OrderSubmission) -> BrokerAcknowledgement: ...

    async def cancel(self, request: CancelRequest) -> BrokerAcknowledgement: ...

    async def fetch_daily_fills(self, trading_date: date) -> DailyFillsObservation: ...


class SubmissionListener(Protocol):
    """체결통보 리스너 부착 판정(ADR-0009 결정 3). 붙어 있지 않으면 제출하지 않는다."""

    async def attached(self, environment: str, now: datetime) -> bool: ...


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

    async def daily_fill_totals(
        self,
        environment: str,
        trading_date: date,
    ) -> InternalDailyTotals: ...

    async def expire_order(
        self,
        order_id: UUID,
        evidence: str,
        occurred_at: datetime,
    ) -> None: ...

    async def save_broker_response(self, raw: RawBrokerResponse) -> None: ...


def _reduction_refusal(order: TrackedOrder | None, quantity: int) -> str | None:
    """부분 취소를 보내기 전에 거절할 이유. 증권사도 초과 취소를 막지만 먼저 우리가 막는다."""
    if order is None:
        return _ORDER_NOT_FOUND
    if quantity <= 0:
        return _INVALID_QUANTITY
    if quantity > order.quantity - order.filled_quantity:
        return _QUANTITY_EXCEEDS_OUTSTANDING
    return None


def _session_key(trading_date: date) -> CalendarSessionKey:
    return CalendarSessionKey(_COUNTRY, _EXCHANGE, trading_date, MarketSessionType.REGULAR)


def _evidence(internal: InternalDailyTotals) -> str:
    """종결 근거를 감사 기록에 남긴다. 이 문자열은 외부 알림 본문에 들어가지 않는다."""
    return f"당일 체결 합계 수량 {internal.filled_quantity} 금액 {internal.filled_amount}"


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
    listener: SubmissionListener
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
        internal = await self.store.daily_fill_totals(environment, trading_date)
        verdict = compare_daily_totals(internal, observation.totals)
        expired, closure_problems = await self._close_session(
            by_client_order_id,
            verdict,
            _evidence(internal),
            now,
        )
        problems = result.problems + closure_problems
        for broker_order_id, problem in problems:
            await self.store.record_reconcile_problem(environment, broker_order_id, problem, now)
        paused = False
        if problems or verdict is AggregateVerdict.MISMATCHED:
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
            problems=problems,
            paused=paused,
            verdict=verdict,
            expired=expired,
        )

    async def _close_session(
        self,
        orders: Mapping[str, TrackedOrder],
        verdict: AggregateVerdict,
        evidence: str,
        now: datetime,
    ) -> tuple[tuple[str, ...], tuple[tuple[str, ReconcileProblem], ...]]:
        """정규장이 끝난 뒤에만 종결을 판단한다. 장중 미체결은 아직 체결될 수 있다."""
        if not session_ended(now):
            return (), ()
        outcomes = close_session_orders(
            tuple(_snapshot(order) for order in orders.values()),
            verdict,
        )
        expired: list[str] = []
        problems: list[tuple[str, ReconcileProblem]] = []
        for outcome in outcomes:
            order = orders[outcome.client_order_id]
            if outcome.closed:
                await self.store.expire_order(order.order_id, evidence, now)
                expired.append(outcome.client_order_id)
            if outcome.problem is not None:
                problems.append((order.broker_order_id or order.client_order_id, outcome.problem))
        return tuple(expired), tuple(problems)

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

    async def reduce_open_quantity(
        self,
        environment: str,
        broker_order_id: str,
        quantity: int,
        now: datetime,
    ) -> ReductionResult:
        """사람이 지정한 미체결 수량만 취소한다(ADR-0013).

        위험검사와 리스너 부착은 요구하지 않는다(결정 3) — 노출을 줄이는 동작은 정책 §3·§4의
        어떤 한도도 새로 위반할 수 없고, 통보가 끊긴 상황에서 위험을 줄일 수단을 막으면 안 된다.
        자동매매 상태도 보지 않는다. 비상정지가 리스너 조건 없이 전량 취소하는 것과 같은 논리다.

        수량은 요청만으로 줄이지 않는다(결정 4·6). 증권사 체결통보가 실제 취소 수량을 실어 올 때
        `apply_notification` 경로가 줄인다 — 취소 요청과 체결이 경합할 수 있기 때문이다.
        """
        trading_date = now.astimezone(_SEOUL).date()
        orders = await self.store.open_orders(environment, trading_date)
        order = next(
            (
                candidate
                for candidate in orders
                if candidate.broker_order_id == broker_order_id
                and candidate.broker_org_no is not None
            ),
            None,
        )
        refusal = _reduction_refusal(order, quantity)
        if refusal is not None or order is None:
            return ReductionResult(
                client_order_id=order.client_order_id if order is not None else "",
                requested_quantity=quantity,
                accepted=False,
                reason_code=refusal,
                cancel_order_id=None,
            )
        acknowledgement = await self._cancel_one(
            environment,
            CancelRequest(
                broker_org_no=order.broker_org_no or "",
                broker_order_id=broker_order_id,
                quantity=quantity,
                partial=True,
            ),
            now,
        )
        await self.store.save_broker_response(acknowledgement.raw)
        if not acknowledgement.accepted:
            await self.store.record_order_event(
                order.order_id,
                _PARTIAL_CANCEL_FAILED,
                f"quantity={quantity} {acknowledgement.message_code}",
                now,
            )
            return ReductionResult(
                client_order_id=order.client_order_id,
                requested_quantity=quantity,
                accepted=False,
                reason_code=acknowledgement.message_code,
                cancel_order_id=None,
            )
        # 결정 5: 취소는 자체 주문번호를 받지만 원주문번호가 살아 있다. 내부 `broker_order_id`는
        # 갱신하지 않고 취소 주문번호를 이벤트에만 남긴다 — 이후 체결은 원주문번호로 온다.
        await self.store.record_order_event(
            order.order_id,
            _PARTIAL_CANCEL_REQUESTED,
            (
                f"quantity={quantity} outstanding={order.quantity - order.filled_quantity} "
                f"cancel_order_id={acknowledgement.broker_order_id or ''}"
            ),
            now,
        )
        return ReductionResult(
            client_order_id=order.client_order_id,
            requested_quantity=quantity,
            accepted=True,
            reason_code=None,
            cancel_order_id=acknowledgement.broker_order_id,
        )

    async def _block_code(
        self,
        environment: str,
        trading_date: date,
        now: datetime,
    ) -> str | None:
        automation = await self.store.automation_record(environment)
        if automation is not None and is_stale_trading_day(automation, trading_date):
            # 정책 §6: 거래일 변경은 어떤 상태에서든 DISABLED 복귀다. 계획 경로와 같은 규칙·사유를
            # 쓴다 — 게이트가 저장된 RUNNING을 그대로 믿으면 어제 켠 상태로 제출된다.
            automation = await self.store.transition_automation(
                AutomationTransition(
                    environment=environment,
                    requested=AutomationState.DISABLED,
                    reason_code=STALE_TRADING_DAY_REASON,
                    occurred_at=now,
                    trading_date=trading_date,
                )
            )
        if automation is None or automation.state is not AutomationState.RUNNING:
            return BlockCode.AUTOMATION_NOT_RUNNING.value
        if not await self._is_trading_day(trading_date):
            return BlockCode.MARKET_CLOSED.value
        if not within_order_window(now, self.limits):
            return BlockCode.MARKET_CLOSED.value
        if not await self.listener.attached(environment, now):
            return BlockCode.LISTENER_NOT_ATTACHED.value
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
