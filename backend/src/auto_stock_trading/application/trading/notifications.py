"""실시간 체결통보 수신 유스케이스. 읽기 전용이며 주문을 제출·취소하지 않는다(ADR-0009)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol
from zoneinfo import ZoneInfo

import anyio

from auto_stock_trading.application.trading.planning import AutomationTransition
from auto_stock_trading.domain.orders.fills import OrderSnapshot, ReconcileProblem
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    InvalidTransitionError,
    OrderState,
    next_order_state,
)
from auto_stock_trading.domain.orders.notifications import (
    NotificationFormatError,
    apply_notification,
    mask_notification_payload,
    parse_notifications,
)
from auto_stock_trading.domain.orders.records import FillNotificationRecord
from auto_stock_trading.domain.risk.limits import BlockCode

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.application.trading.submission import TrackedOrder
    from auto_stock_trading.domain.orders.notifications import FillNotification
    from auto_stock_trading.domain.orders.records import AutomationRecord

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_ATTACHED: Final = "LISTENER_ATTACHED"
_DETACHED: Final = "LISTENER_DETACHED"
_FAILED: Final = "LISTENER_ERROR"
_SUPERSEDED: Final = "SUPERSEDED"
_PROCESS_START: Final = "PROCESS_START"
# 증권사는 주문 접수 HTTP 응답을 돌려주기 전에 통보를 밀어준다. 그래서 우리 주문번호 커밋보다
# 통보가 먼저 도착할 수 있다(2026-08-20 실측: 주문 5건 중 2건). 조회를 몇 번 다시 해 본 뒤에만
# 설명할 수 없는 불일치로 판정한다.
# 실측 2026-08-20: 1초 창으로는 부족했다(제출 3건 중 1건이 오탐). 접수 응답과 커밋 지연을 덮도록
# 5초로 넓힌다. 실제 외부 주문은 재조회해도 계속 없으므로 검출이 늦어질 뿐 사라지지 않는다.
_UNMATCHED_RETRIES: Final = 10
_UNMATCHED_DELAY_SECONDS: Final = 0.5
_PAUSABLE: Final = frozenset({AutomationState.ARMED, AutomationState.RUNNING})


@dataclass(frozen=True, slots=True)
class NotificationOutcome:
    broker_order_id: str
    client_order_id: str | None
    state: OrderState | None
    problem: ReconcileProblem | None


@dataclass(frozen=True, slots=True)
class HandleResult:
    outcomes: tuple[NotificationOutcome, ...]
    blocked: bool


@dataclass(frozen=True, slots=True)
class AttachResult:
    session_id: UUID
    blocked: bool


class NotificationOrders(Protocol):
    """주문·자동매매 쪽 협력자. 기존 주문 저장소가 그대로 만족한다."""

    async def automation_record(self, environment: str) -> AutomationRecord | None: ...

    async def transition_automation(
        self,
        transition: AutomationTransition,
    ) -> AutomationRecord: ...

    async def open_orders(
        self,
        environment: str,
        trading_date: date,
    ) -> tuple[TrackedOrder, ...]: ...

    async def record_reconcile_problem(
        self,
        environment: str,
        broker_order_id: str,
        problem: ReconcileProblem,
        occurred_at: datetime,
    ) -> None: ...


class NotificationSink(Protocol):
    """통보 저장과 리스너 세션. 통보 저장과 주문 상태 전이는 같은 트랜잭션이다."""

    async def order_by_broker_order_id(
        self,
        environment: str,
        broker_order_id: str,
    ) -> TrackedOrder | None: ...

    async def record_notification(self, record: FillNotificationRecord) -> None: ...

    async def start_session(
        self,
        environment: str,
        transaction_id: str,
        at: datetime,
    ) -> UUID: ...

    async def close_open_sessions(self, environment: str, reason: str, at: datetime) -> int: ...

    async def heartbeat(self, session_id: UUID, at: datetime) -> None: ...

    async def end_session(self, session_id: UUID, reason: str, at: datetime) -> None: ...

    async def record_listener_event(
        self,
        environment: str,
        reason_code: str,
        detail: str,
        occurred_at: datetime,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PendingNotification:
    """대조 실패로 반영되지 않은 저장된 통보. 본문은 마스킹된 그대로다."""

    notification_id: UUID
    payload: str
    received_at: datetime
    problem: str


@dataclass(frozen=True, slots=True)
class ReplayApplication:
    """재반영 한 건. 전이와 해소 표시를 같은 트랜잭션에 넣기 위한 입력이다."""

    notification_id: UUID
    order_id: UUID
    state: OrderState
    filled_quantity: int
    average_fill_price: Decimal | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    applied: int
    unresolved: int
    unreadable: int


class NotificationReplayStore(Protocol):
    async def pending_notifications(
        self,
        environment: str,
    ) -> tuple[PendingNotification, ...]: ...

    async def order_by_broker_order_id(
        self,
        environment: str,
        broker_order_id: str,
    ) -> TrackedOrder | None: ...

    async def apply_replay(self, application: ReplayApplication) -> None: ...


@dataclass(frozen=True, slots=True)
class NotificationReplay:
    """대조 버그로 반영되지 않은 저장된 증권사 사실을 다시 반영한다.

    사람의 진술이 아니라 이미 저장된 증권사 통보를 적용하는 것이므로 ADR-0010의 종결 경로와 다르다.
    한 번 반영된 통보는 `resolved_at`이 채워져 다시 대상이 되지 않는다.
    """

    store: NotificationReplayStore
    environment: str

    async def replay(self, now: datetime) -> ReplaySummary:
        applied = 0
        unresolved = 0
        unreadable = 0
        for pending in await self.store.pending_notifications(self.environment):
            try:
                notifications = parse_notifications(pending.payload)
            except NotificationFormatError:
                unreadable += 1
                continue
            for notification in notifications:
                if await self._apply_one(pending, notification, now):
                    applied += 1
                else:
                    unresolved += 1
        return ReplaySummary(applied=applied, unresolved=unresolved, unreadable=unreadable)

    async def _apply_one(
        self,
        pending: PendingNotification,
        notification: FillNotification,
        now: datetime,
    ) -> bool:
        order = await self.store.order_by_broker_order_id(
            self.environment,
            notification.matched_broker_order_id,
        )
        if order is None:
            return False
        result = apply_notification(_snapshot(order), notification)
        if result.problem is not None or not result.changed:
            return False
        if not _allowed(order, result.state):
            return False
        await self.store.apply_replay(
            ReplayApplication(
                notification_id=pending.notification_id,
                order_id=order.order_id,
                state=result.state,
                filled_quantity=result.filled_quantity,
                average_fill_price=result.average_fill_price,
                occurred_at=now,
            )
        )
        return True


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


def _allowed(order: TrackedOrder, state: OrderState) -> bool:
    """상태 그래프가 막는 전이는 사실 반영이 아니라 대조 불일치로 다룬다."""
    try:
        _ = next_order_state(order.state, state)
    except InvalidTransitionError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class FillNotificationListener:
    orders: NotificationOrders
    notifications: NotificationSink
    environment: str
    account_reference: str
    unmatched_retries: int = _UNMATCHED_RETRIES
    unmatched_delay_seconds: float = _UNMATCHED_DELAY_SECONDS

    async def reset_on_start(self, now: datetime) -> AutomationState:
        """프로세스 시작 시 자동매매를 DISABLED로 돌린다(정책 §6).

        리스너는 거래 관련 유일한 상시 프로세스다. 세션 내부 재연결은 프로세스 시작이 아니므로
        여기서만 호출한다. 사람이 다시 armed·running으로 올려야 주문이 나갈 수 있다.
        """
        record = await self.orders.automation_record(self.environment)
        if record is None or record.state is AutomationState.DISABLED:
            return AutomationState.DISABLED
        applied = await self.orders.transition_automation(
            AutomationTransition(
                environment=self.environment,
                requested=AutomationState.DISABLED,
                reason_code=_PROCESS_START,
                occurred_at=now,
                trading_date=now.astimezone(_SEOUL).date(),
            )
        )
        return applied.state

    async def attach(self, transaction_id: str, now: datetime) -> AttachResult:
        """세션을 시작한다. 미체결 주문이 있으면 놓친 통보가 있을 수 있어 차단한다."""
        _ = await self.notifications.close_open_sessions(self.environment, _SUPERSEDED, now)
        session_id = await self.notifications.start_session(self.environment, transaction_id, now)
        await self.notifications.record_listener_event(
            self.environment,
            _ATTACHED,
            transaction_id,
            now,
        )
        open_orders = await self.orders.open_orders(self.environment, now.astimezone(_SEOUL).date())
        if not open_orders:
            return AttachResult(session_id=session_id, blocked=False)
        for order in open_orders:
            await self._record_problem(
                order.broker_order_id or order.client_order_id,
                ReconcileProblem.NOTIFICATION_GAP,
                now,
            )
        await self._pause(now)
        return AttachResult(session_id=session_id, blocked=True)

    async def heartbeat(self, session_id: UUID, now: datetime) -> None:
        await self.notifications.heartbeat(session_id, now)

    async def record_failure(self, detail: str, now: datetime) -> None:
        """세션 수준 실패를 남긴다. 세션이 닫히면 제출 게이트가 이미 차단한다."""
        await self.notifications.record_listener_event(self.environment, _FAILED, detail, now)

    async def detach(self, session_id: UUID, reason: str, now: datetime) -> None:
        await self.notifications.end_session(session_id, reason, now)
        await self.notifications.record_listener_event(self.environment, _DETACHED, reason, now)

    async def handle(self, payload: str, received_at: datetime) -> HandleResult:
        """복호화된 프레임 하나를 반영한다. 형식 위반은 체결 유실 가능성으로 다룬다."""
        try:
            notifications = parse_notifications(payload)
        except NotificationFormatError as error:
            # 사유는 형식 위반의 종류뿐이다. 본문은 어디에도 남기지 않는다.
            await self.notifications.record_listener_event(
                self.environment,
                ReconcileProblem.NOTIFICATION_UNPARSABLE.value,
                error.detail,
                received_at,
            )
            await self._record_problem("", ReconcileProblem.NOTIFICATION_UNPARSABLE, received_at)
            await self._pause(received_at)
            return HandleResult(outcomes=(), blocked=True)
        outcomes: list[NotificationOutcome] = []
        blocked = False
        masked = mask_notification_payload(payload)
        for notification in notifications:
            outcome = await self._apply(notification, masked, received_at)
            outcomes.append(outcome)
            blocked = blocked or outcome.problem is not None
        if blocked:
            await self._pause(received_at)
        return HandleResult(outcomes=tuple(outcomes), blocked=blocked)

    async def _apply(
        self,
        notification: FillNotification,
        masked_payload: str,
        received_at: datetime,
    ) -> NotificationOutcome:
        order = await self._order_for(notification.matched_broker_order_id)
        if order is None:
            return await self._unmatched(notification, masked_payload, received_at)
        result = apply_notification(_snapshot(order), notification)
        problem = result.problem
        # 부분 취소는 상태를 바꾸지 않고 수량만 줄인다(ADR-0013 결정 6). 같은 상태로의 전이를
        # 상태 그래프에 물어보면 거부되므로, 상태가 그대로일 때는 전이 검사를 하지 않는다.
        reduced = result.quantity if result.quantity != order.quantity else None
        state = result.state if result.changed and result.state is not order.state else None
        if state is not None and not _allowed(order, state):
            problem = ReconcileProblem.TERMINAL_STATE_CHANGED
            state = None
        if problem is not None:
            state = None
            reduced = None
        await self.notifications.record_notification(
            FillNotificationRecord(
                environment=self.environment,
                account_reference=self.account_reference,
                order_id=order.order_id,
                notification=notification,
                masked_payload=masked_payload,
                problem=problem,
                state=state,
                quantity=reduced,
                filled_quantity=None if state is None else result.filled_quantity,
                average_fill_price=None if state is None else result.average_fill_price,
                received_at=received_at,
            )
        )
        if problem is not None:
            await self.orders.record_reconcile_problem(
                self.environment,
                notification.broker_order_id,
                problem,
                received_at,
            )
        return NotificationOutcome(
            broker_order_id=notification.broker_order_id,
            client_order_id=order.client_order_id,
            state=state,
            problem=problem,
        )

    async def _order_for(self, broker_order_id: str) -> TrackedOrder | None:
        """통보가 우리 커밋보다 먼저 올 수 있으므로 잠깐 기다리며 다시 찾는다."""
        for attempt in range(self.unmatched_retries + 1):
            order = await self.notifications.order_by_broker_order_id(
                self.environment,
                broker_order_id,
            )
            if order is not None:
                return order
            if attempt < self.unmatched_retries:
                await anyio.sleep(self.unmatched_delay_seconds)
        return None

    async def _unmatched(
        self,
        notification: FillNotification,
        masked_payload: str,
        received_at: datetime,
    ) -> NotificationOutcome:
        problem = ReconcileProblem.UNKNOWN_BROKER_ORDER
        await self.notifications.record_notification(
            FillNotificationRecord(
                environment=self.environment,
                account_reference=self.account_reference,
                order_id=None,
                notification=notification,
                masked_payload=masked_payload,
                problem=problem,
                state=None,
                quantity=None,
                filled_quantity=None,
                average_fill_price=None,
                received_at=received_at,
            )
        )
        await self.orders.record_reconcile_problem(
            self.environment,
            notification.matched_broker_order_id,
            problem,
            received_at,
        )
        return NotificationOutcome(
            broker_order_id=notification.matched_broker_order_id,
            client_order_id=None,
            state=None,
            problem=problem,
        )

    async def _record_problem(
        self,
        broker_order_id: str,
        problem: ReconcileProblem,
        occurred_at: datetime,
    ) -> None:
        await self.orders.record_reconcile_problem(
            self.environment,
            broker_order_id,
            problem,
            occurred_at,
        )

    async def _pause(self, now: datetime) -> None:
        """정지할 수 있는 상태에서만 전이한다. 이미 멈춰 있으면 기록만 남는다."""
        record = await self.orders.automation_record(self.environment)
        if record is None or record.state not in _PAUSABLE:
            return
        _ = await self.orders.transition_automation(
            AutomationTransition(
                environment=self.environment,
                requested=AutomationState.PAUSED,
                reason_code=BlockCode.ACCOUNT_NOT_RECONCILED.value,
                occurred_at=now,
                trading_date=now.astimezone(_SEOUL).date(),
            )
        )
