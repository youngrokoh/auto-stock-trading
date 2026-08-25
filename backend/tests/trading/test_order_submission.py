from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import anyio
import pytest

from auto_stock_trading.adapters.brokers.kis_orders import (
    BrokerAcknowledgement,
    CancelRequest,
    DailyFillsObservation,
    OrderSubmission,
)
from auto_stock_trading.application.trading.submission import (
    OrderSubmitter,
    SubmissionInput,
    TrackedOrder,
)
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse
from auto_stock_trading.domain.orders.fills import BrokerFill, ReconcileProblem
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide, OrderState
from auto_stock_trading.domain.orders.records import AutomationRecord
from auto_stock_trading.domain.orders.session_close import (
    AggregateVerdict,
    BrokerDailyTotals,
    InternalDailyTotals,
)
from auto_stock_trading.domain.risk.limits import BlockCode
from tests.trading.calendar_fixture import trading_day_record

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.calendar import (
        CalendarSessionKey,
        MarketCalendarRecord,
    )

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_ENVIRONMENT: Final = "paper"
_TRADING_DATE: Final = date(2026, 8, 19)
_NOW: Final = datetime.combine(_TRADING_DATE, time(10, 11), _SEOUL)
_AFTER_HOURS: Final = datetime.combine(_TRADING_DATE, time(17, 22), _SEOUL)
_PRICE: Final = Decimal(71_800)
_ORDER_ID: Final = UUID("00000000-0000-4000-8000-000000000401")
_PLAN_ID: Final = UUID("00000000-0000-4000-8000-000000000301")
_RAW: Final = RawBrokerResponse(
    operation=BrokerOperation.ORDER_SUBMIT,
    endpoint="/uapi/domestic-stock/v1/trading/order-cash",
    request_fingerprint="order_submit:hash:005930:buy:1",
    received_at=_NOW.astimezone(UTC),
    payload_json='{"rt_cd":"0"}',
)


def _tracked(  # noqa: PLR0913 — 테스트 주문 조립기라 필드를 그대로 노출한다
    *,
    order_id: UUID = _ORDER_ID,
    client_order_id: str = "a" * 32,
    state: OrderState = OrderState.PLANNED,
    quantity: int = 1,
    filled_quantity: int = 0,
    broker_order_id: str | None = None,
    broker_org_no: str | None = None,
) -> TrackedOrder:
    return TrackedOrder(
        order_id=order_id,
        plan_id=_PLAN_ID,
        client_order_id=client_order_id,
        symbol="005930",
        side=OrderSide.BUY,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=None,
        limit_price=_PRICE,
        state=state,
        broker_order_id=broker_order_id,
        broker_org_no=broker_org_no,
    )


@final
class FakeCalendar:
    def __init__(self, *, trading_day: bool = True) -> None:
        self._trading_day = trading_day

    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None:
        return trading_day_record(key) if self._trading_day else None


@dataclass
class FakeBroker:
    acknowledgement: BrokerAcknowledgement = _RAW and BrokerAcknowledgement(
        accepted=True,
        broker_order_id="0000117057",
        broker_org_no="00950",
        broker_order_time="101153",
        message_code="APBK0013",
        message="주문 전송 완료 되었습니다.",
        raw=_RAW,
    )
    fills: tuple[BrokerFill, ...] = ()
    totals: BrokerDailyTotals | None = None
    submissions: list[OrderSubmission] = field(default_factory=list)
    cancels: list[CancelRequest] = field(default_factory=list)
    fill_queries: list[date] = field(default_factory=list)
    failure: Exception | None = None

    async def submit(self, submission: OrderSubmission) -> BrokerAcknowledgement:
        if self.failure is not None:
            raise self.failure
        self.submissions.append(submission)
        return self.acknowledgement

    async def cancel(self, request: CancelRequest) -> BrokerAcknowledgement:
        if self.failure is not None:
            raise self.failure
        self.cancels.append(request)
        return self.acknowledgement

    async def fetch_daily_fills(self, trading_date: date) -> DailyFillsObservation:
        if self.failure is not None:
            raise self.failure
        self.fill_queries.append(trading_date)
        return DailyFillsObservation(fills=self.fills, raw=_RAW, totals=self.totals)


@dataclass
class FakeStore:
    automation: AutomationState = AutomationState.RUNNING
    daily_fill_totals_value: InternalDailyTotals | None = None
    expired_orders: list[tuple[UUID, str]] = field(default_factory=list)
    automation_trading_date: date = _TRADING_DATE
    pending: tuple[TrackedOrder, ...] = ()
    open_orders_rows: tuple[TrackedOrder, ...] = ()
    submissions: list[tuple[UUID, str, str]] = field(default_factory=list)
    rejections: list[tuple[UUID, str]] = field(default_factory=list)
    fills_applied: list[tuple[UUID, OrderState, int]] = field(default_factory=list)
    events: list[tuple[UUID, str, str | None]] = field(default_factory=list)
    problems: list[tuple[str, ReconcileProblem]] = field(default_factory=list)
    transitions: list[tuple[AutomationState, str]] = field(default_factory=list)
    api_failures: list[str] = field(default_factory=list)
    raw_responses: list[str] = field(default_factory=list)

    async def automation_record(self, environment: str) -> AutomationRecord | None:
        return AutomationRecord(
            environment=environment,
            state=self.automation,
            reason_code=None,
            trading_date=self.automation_trading_date,
            changed_at=_NOW,
        )

    async def pending_orders(
        self,
        environment: str,
        trading_date: date,
        plan_id: UUID | None,
    ) -> tuple[TrackedOrder, ...]:
        _ = (environment, trading_date)
        if plan_id is None:
            return self.pending
        return tuple(order for order in self.pending if order.plan_id == plan_id)

    async def open_orders(self, environment: str, trading_date: date) -> tuple[TrackedOrder, ...]:
        _ = (environment, trading_date)
        return self.open_orders_rows

    async def record_submission(
        self,
        order_id: UUID,
        acknowledgement: BrokerAcknowledgement,
        submitted_at: datetime,
    ) -> None:
        _ = submitted_at
        self.submissions.append(
            (
                order_id,
                acknowledgement.broker_order_id or "",
                acknowledgement.broker_org_no or "",
            )
        )

    async def record_rejection(
        self,
        order_id: UUID,
        acknowledgement: BrokerAcknowledgement,
        occurred_at: datetime,
    ) -> None:
        _ = occurred_at
        self.rejections.append((order_id, acknowledgement.message_code))

    async def apply_fill(
        self,
        order_id: UUID,
        state: OrderState,
        filled_quantity: int,
        average_fill_price: Decimal | None,
        occurred_at: datetime,
    ) -> None:
        _ = (average_fill_price, occurred_at)
        self.fills_applied.append((order_id, state, filled_quantity))

    async def record_order_event(
        self,
        order_id: UUID,
        event_type: str,
        detail: str | None,
        occurred_at: datetime,
    ) -> None:
        _ = occurred_at
        self.events.append((order_id, event_type, detail))

    async def record_reconcile_problem(
        self,
        environment: str,
        broker_order_id: str,
        problem: ReconcileProblem,
        occurred_at: datetime,
    ) -> None:
        _ = (environment, occurred_at)
        self.problems.append((broker_order_id, problem))

    async def transition_automation(self, transition: object) -> AutomationRecord:
        requested = getattr(transition, "requested", AutomationState.DISABLED)
        reason = str(getattr(transition, "reason_code", ""))
        self.transitions.append((requested, reason))
        self.automation = requested
        return AutomationRecord(
            environment=_ENVIRONMENT,
            state=requested,
            reason_code=reason,
            trading_date=_TRADING_DATE,
            changed_at=_NOW,
        )

    async def record_api_failure(
        self,
        environment: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        _ = (environment, occurred_at)
        self.api_failures.append(detail)

    async def expire_order(self, order_id: UUID, evidence: str, occurred_at: datetime) -> None:
        _ = occurred_at
        self.expired_orders.append((order_id, evidence))

    async def daily_fill_totals(self, environment: str, trading_date: date) -> InternalDailyTotals:
        _ = (environment, trading_date)
        return self.daily_fill_totals_value or InternalDailyTotals(0, Decimal(0))

    async def save_broker_response(self, raw: RawBrokerResponse) -> None:
        self.raw_responses.append(raw.request_fingerprint)


@dataclass
class FakeListener:
    """체결통보 리스너 부착 여부. 기본은 부착 상태다."""

    attached_result: bool = True

    async def attached(self, environment: str, now: datetime) -> bool:
        assert environment == _ENVIRONMENT
        assert now is not None
        return self.attached_result


def _submitter(
    store: FakeStore,
    broker: FakeBroker,
    *,
    trading_day: bool = True,
    listener_attached: bool = True,
) -> OrderSubmitter:
    return OrderSubmitter(
        calendar=FakeCalendar(trading_day=trading_day),
        broker=broker,
        store=store,
        listener=FakeListener(attached_result=listener_attached),
    )


def test_submission_without_an_attached_listener_never_calls_the_broker() -> None:
    async def scenario() -> None:
        store = FakeStore(pending=(_tracked(),))
        broker = FakeBroker()

        result = await _submitter(store, broker, listener_attached=False).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            _NOW,
        )

        assert result.block_code == BlockCode.LISTENER_NOT_ATTACHED.value
        assert result.submitted == ()
        assert broker.submissions == []

    anyio.run(scenario)


def test_planned_order_is_submitted_and_recorded() -> None:
    async def scenario() -> None:
        store = FakeStore(pending=(_tracked(),))
        broker = FakeBroker()

        result = await _submitter(store, broker).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            _NOW,
        )

        assert result.block_code is None
        assert result.submitted == ("a" * 32,)
        assert result.rejected == ()
        (submission,) = broker.submissions
        assert submission.symbol == "005930"
        assert submission.quantity == 1
        assert submission.limit_price == _PRICE
        assert store.submissions == [(_ORDER_ID, "0000117057", "00950")]

    anyio.run(scenario)


def test_submission_outside_the_order_window_never_calls_the_broker() -> None:
    async def scenario() -> None:
        store = FakeStore(pending=(_tracked(),))
        broker = FakeBroker()

        result = await _submitter(store, broker).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            _AFTER_HOURS,
        )

        assert result.block_code == BlockCode.MARKET_CLOSED.value
        assert result.submitted == ()
        assert broker.submissions == []

    anyio.run(scenario)


def test_submission_on_a_non_trading_day_is_blocked() -> None:
    async def scenario() -> None:
        store = FakeStore(pending=(_tracked(),))
        broker = FakeBroker()

        result = await _submitter(store, broker, trading_day=False).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            _NOW,
        )

        assert result.block_code == BlockCode.MARKET_CLOSED.value
        assert broker.submissions == []

    anyio.run(scenario)


def test_submission_requires_running_automation() -> None:
    async def scenario() -> None:
        store = FakeStore(automation=AutomationState.PAUSED, pending=(_tracked(),))
        broker = FakeBroker()

        result = await _submitter(store, broker).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            _NOW,
        )

        assert result.block_code == BlockCode.AUTOMATION_NOT_RUNNING.value
        assert broker.submissions == []

    anyio.run(scenario)


def test_submission_resets_a_stale_trading_day_before_submitting() -> None:
    """정책 §6은 거래일 변경 시 **항상** DISABLED다. 리셋이 계획 경로에만 있으면 안 된다.

    제출 게이트가 저장된 RUNNING을 그대로 믿으면, 계획을 돌리지 않은 날에도 자동매매가 켜져
    있는 것으로 판정된다.
    """

    async def scenario() -> None:
        store = FakeStore(pending=(_tracked(),))
        store.automation_trading_date = date(2026, 8, 21)
        broker = FakeBroker()

        result = await _submitter(store, broker).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            _NOW,
        )

        assert result.block_code == BlockCode.AUTOMATION_NOT_RUNNING.value
        assert broker.submissions == []
        # 감사 기록이 계획 경로와 같은 사유를 남겨야 원인이 하나로 읽힌다.
        assert store.transitions == [(AutomationState.DISABLED, "TRADING_DAY_CHANGED")]

    anyio.run(scenario)


def test_already_submitted_orders_are_not_sent_again() -> None:
    async def scenario() -> None:
        store = FakeStore(pending=())
        broker = FakeBroker()

        result = await _submitter(store, broker).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            _NOW,
        )

        assert result.submitted == ()
        assert broker.submissions == []

    anyio.run(scenario)


def test_broker_rejection_is_stored_with_the_message_code() -> None:
    async def scenario() -> None:
        store = FakeStore(pending=(_tracked(),))
        broker = FakeBroker(
            acknowledgement=BrokerAcknowledgement(
                accepted=False,
                broker_order_id=None,
                broker_org_no=None,
                broker_order_time=None,
                message_code="APBK0919",
                message="주문가능금액이 부족합니다.",
                raw=_RAW,
            )
        )

        result = await _submitter(store, broker).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            _NOW,
        )

        assert result.submitted == ()
        assert result.rejected == (("a" * 32, "APBK0919"),)
        assert store.rejections == [(_ORDER_ID, "APBK0919")]

    anyio.run(scenario)


def test_transport_failure_records_an_api_failure_and_stops() -> None:
    async def scenario() -> None:
        second = _tracked(order_id=uuid4(), client_order_id="b" * 32)
        store = FakeStore(pending=(_tracked(), second))
        broker = FakeBroker(failure=TimeoutError("timeout"))

        with pytest.raises(TimeoutError):
            _ = await _submitter(store, broker).submit(
                SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
                _NOW,
            )

        assert store.api_failures == ["order_submit:TimeoutError"]
        assert store.submissions == []

    anyio.run(scenario)


def test_only_the_requested_plan_is_submitted() -> None:
    async def scenario() -> None:
        other_plan = replace(_tracked(order_id=uuid4(), client_order_id="c" * 32), plan_id=uuid4())
        store = FakeStore(pending=(_tracked(), other_plan))
        broker = FakeBroker()

        result = await _submitter(store, broker).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=_PLAN_ID),
            _NOW,
        )

        assert result.submitted == ("a" * 32,)
        assert len(broker.submissions) == 1

    anyio.run(scenario)


def test_synchronize_applies_broker_fills() -> None:
    async def scenario() -> None:
        tracked = _tracked(
            state=OrderState.SUBMITTED,
            quantity=3,
            broker_order_id="0000117057",
            broker_org_no="00950",
        )
        store = FakeStore(open_orders_rows=(tracked,))
        broker = FakeBroker(
            fills=(
                BrokerFill(
                    broker_order_id="0000117057",
                    symbol="005930",
                    order_quantity=3,
                    filled_quantity=3,
                    remaining_quantity=0,
                    rejected_quantity=0,
                    canceled=False,
                    average_fill_price=_PRICE,
                ),
            )
        )

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _NOW)

        assert summary.updated == (("a" * 32, OrderState.FILLED),)
        assert summary.problems == ()
        assert summary.paused is False
        assert store.fills_applied == [(_ORDER_ID, OrderState.FILLED, 3)]
        assert broker.fill_queries == [_TRADING_DATE]
        assert store.raw_responses == ["order_submit:hash:005930:buy:1"]

    anyio.run(scenario)


def test_synchronize_pauses_automation_on_reconcile_problems() -> None:
    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(_tracked(state=OrderState.SUBMITTED, broker_order_id="0000117057"),)
        )
        broker = FakeBroker(
            fills=(
                BrokerFill(
                    broker_order_id="0000999999",
                    symbol="005930",
                    order_quantity=1,
                    filled_quantity=1,
                    remaining_quantity=0,
                    rejected_quantity=0,
                    canceled=False,
                    average_fill_price=_PRICE,
                ),
            )
        )

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _NOW)

        assert summary.problems == (("0000999999", ReconcileProblem.UNKNOWN_BROKER_ORDER),)
        assert summary.paused is True
        assert store.problems == [("0000999999", ReconcileProblem.UNKNOWN_BROKER_ORDER)]
        assert store.transitions == [
            (AutomationState.PAUSED, BlockCode.ACCOUNT_NOT_RECONCILED.value)
        ]

    anyio.run(scenario)


def test_synchronize_outside_the_order_window_still_reads_broker_facts() -> None:
    """조회는 주문 허용시간 밖에서도 수행한다. 마감 후 재대조가 그 시간대에 일어난다."""

    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(_tracked(state=OrderState.SUBMITTED, broker_order_id="0000117057"),),
            daily_fill_totals_value=InternalDailyTotals(0, Decimal(0)),
        )
        broker = FakeBroker(totals=BrokerDailyTotals(0, Decimal(0)))

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _AFTER_HOURS)

        assert summary.problems == ()
        assert broker.fill_queries == [_TRADING_DATE]

    anyio.run(scenario)


def test_synchronize_failure_records_an_api_failure() -> None:
    async def scenario() -> None:
        store = FakeStore()
        broker = FakeBroker(failure=TimeoutError("timeout"))

        with pytest.raises(TimeoutError):
            _ = await _submitter(store, broker).synchronize(_ENVIRONMENT, _NOW)

        assert store.api_failures == ["order_fills:TimeoutError"]

    anyio.run(scenario)


def test_cancel_open_orders_requests_cancellation_for_each_open_order() -> None:
    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(
                _tracked(
                    state=OrderState.SUBMITTED,
                    quantity=3,
                    broker_order_id="0000117057",
                    broker_org_no="00950",
                ),
                _tracked(
                    order_id=UUID("00000000-0000-4000-8000-000000000402"),
                    client_order_id="b" * 32,
                    state=OrderState.PARTIALLY_FILLED,
                    quantity=2,
                    filled_quantity=1,
                    broker_order_id="0000117058",
                    broker_org_no="00950",
                ),
            )
        )
        broker = FakeBroker()

        summary = await _submitter(store, broker).cancel_open_orders(
            _ENVIRONMENT,
            _NOW,
            "EMERGENCY_STOP",
        )

        assert summary.requested == ("a" * 32, "b" * 32)
        assert summary.failed == ()
        assert [request.broker_order_id for request in broker.cancels] == [
            "0000117057",
            "0000117058",
        ]
        assert [request.quantity for request in broker.cancels] == [3, 1]
        assert [event[1] for event in store.events] == ["cancel_requested", "cancel_requested"]
        assert len(store.raw_responses) == 2

    anyio.run(scenario)


def test_cancel_failure_is_reported_and_does_not_stop_other_orders() -> None:
    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(
                _tracked(
                    state=OrderState.SUBMITTED,
                    broker_order_id="0000117057",
                    broker_org_no="00950",
                ),
            )
        )
        broker = FakeBroker(
            acknowledgement=BrokerAcknowledgement(
                accepted=False,
                broker_order_id=None,
                broker_org_no=None,
                broker_order_time=None,
                message_code="APBK0918",
                message="취소가능수량이 없습니다.",
                raw=_RAW,
            )
        )

        summary = await _submitter(store, broker).cancel_open_orders(
            _ENVIRONMENT,
            _NOW,
            "EMERGENCY_STOP",
        )

        assert summary.requested == ()
        assert summary.failed == (("a" * 32, "APBK0918"),)
        assert [event[1] for event in store.events] == ["cancel_failed"]

    anyio.run(scenario)


def test_cancel_skips_orders_without_broker_identifiers() -> None:
    async def scenario() -> None:
        store = FakeStore(open_orders_rows=(_tracked(state=OrderState.PLANNED),))
        broker = FakeBroker()

        summary = await _submitter(store, broker).cancel_open_orders(
            _ENVIRONMENT,
            _NOW,
            "EMERGENCY_STOP",
        )

        assert summary.requested == ()
        assert summary.failed == ()
        assert broker.cancels == []

    anyio.run(scenario)


def test_submission_uses_the_seoul_trading_date() -> None:
    async def scenario() -> None:
        store = FakeStore(pending=(_tracked(),))
        broker = FakeBroker()
        midnight_utc = _NOW.astimezone(UTC) - timedelta(hours=0)

        _ = await _submitter(store, broker).submit(
            SubmissionInput(environment=_ENVIRONMENT, plan_id=None),
            midnight_utc,
        )

        assert len(broker.submissions) == 1

    anyio.run(scenario)


def test_partial_cancel_sends_the_human_quantity_and_records_the_cancel_order_number() -> None:
    """ADR-0013 결정 2·5·6: 사람이 정한 수량만 보내고, 취소 주문번호는 이벤트에만 남는다."""

    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(
                _tracked(
                    state=OrderState.SUBMITTED,
                    quantity=14,
                    broker_order_id="0000117057",
                    broker_org_no="00950",
                ),
            )
        )
        broker = FakeBroker(
            acknowledgement=BrokerAcknowledgement(
                accepted=True,
                broker_order_id="0000117090",
                broker_org_no="00950",
                broker_order_time="101153",
                message_code="APBK0013",
                message="주문 전송 완료 되었습니다.",
                raw=_RAW,
            )
        )

        result = await _submitter(store, broker).reduce_open_quantity(
            _ENVIRONMENT,
            "0000117057",
            5,
            _NOW,
        )

        assert result.accepted is True
        assert result.reason_code is None
        assert result.cancel_order_id == "0000117090"
        (request,) = broker.cancels
        assert request.broker_order_id == "0000117057"
        assert request.quantity == 5
        assert request.partial is True
        (event,) = store.events
        assert event[1] == "partial_cancel_requested"
        assert event[2] is not None
        assert "0000117090" in event[2]
        # 결정 4·6: 수량은 통보로 확인될 때만 줄어든다. 요청만으로 상태·수량을 바꾸지 않는다.
        assert store.fills_applied == []

    anyio.run(scenario)


def test_partial_cancel_beyond_the_outstanding_quantity_is_refused_locally() -> None:
    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(
                _tracked(
                    state=OrderState.PARTIALLY_FILLED,
                    quantity=14,
                    filled_quantity=10,
                    broker_order_id="0000117057",
                    broker_org_no="00950",
                ),
            )
        )
        broker = FakeBroker()

        result = await _submitter(store, broker).reduce_open_quantity(
            _ENVIRONMENT,
            "0000117057",
            5,
            _NOW,
        )

        assert result.accepted is False
        assert result.reason_code == "QUANTITY_EXCEEDS_OUTSTANDING"
        assert broker.cancels == []
        assert store.events == []

    anyio.run(scenario)


def test_partial_cancel_of_an_unknown_order_is_refused_without_calling_the_broker() -> None:
    async def scenario() -> None:
        store = FakeStore()
        broker = FakeBroker()

        result = await _submitter(store, broker).reduce_open_quantity(
            _ENVIRONMENT,
            "0000999999",
            1,
            _NOW,
        )

        assert result.accepted is False
        assert result.reason_code == "ORDER_NOT_FOUND"
        assert broker.cancels == []

    anyio.run(scenario)


def test_partial_cancel_rejection_records_the_message_code_and_changes_nothing() -> None:
    """실측 `40430000`(취소수량 초과) 경로. 결정 7: 거절은 fail-closed다."""

    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(
                _tracked(
                    state=OrderState.SUBMITTED,
                    quantity=14,
                    broker_order_id="0000117057",
                    broker_org_no="00950",
                ),
            )
        )
        broker = FakeBroker(
            acknowledgement=BrokerAcknowledgement(
                accepted=False,
                broker_order_id=None,
                broker_org_no=None,
                broker_order_time=None,
                message_code="40430000",
                message="취소수량이 취소가능수량을 초과합니다.",
                raw=_RAW,
            )
        )

        result = await _submitter(store, broker).reduce_open_quantity(
            _ENVIRONMENT,
            "0000117057",
            5,
            _NOW,
        )

        assert result.accepted is False
        assert result.reason_code == "40430000"
        assert [event[1] for event in store.events] == ["partial_cancel_failed"]
        assert store.fills_applied == []
        assert len(store.raw_responses) == 1

    anyio.run(scenario)


def test_partial_cancel_does_not_require_a_listener_or_a_running_automation() -> None:
    """ADR-0013 결정 3: 노출 축소는 위험검사·리스너 조건을 면제한다."""

    async def scenario() -> None:
        store = FakeStore(
            automation=AutomationState.DISABLED,
            open_orders_rows=(
                _tracked(
                    state=OrderState.SUBMITTED,
                    quantity=14,
                    broker_order_id="0000117057",
                    broker_org_no="00950",
                ),
            ),
        )
        broker = FakeBroker()

        result = await _submitter(store, broker, listener_attached=False).reduce_open_quantity(
            _ENVIRONMENT,
            "0000117057",
            5,
            _NOW,
        )

        assert result.accepted is True
        assert len(broker.cancels) == 1

    anyio.run(scenario)


def test_partial_cancel_transport_failure_records_an_api_failure() -> None:
    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(
                _tracked(
                    state=OrderState.SUBMITTED,
                    quantity=14,
                    broker_order_id="0000117057",
                    broker_org_no="00950",
                ),
            )
        )
        broker = FakeBroker(failure=TimeoutError("timeout"))

        with pytest.raises(TimeoutError):
            _ = await _submitter(store, broker).reduce_open_quantity(
                _ENVIRONMENT,
                "0000117057",
                5,
                _NOW,
            )

        assert store.api_failures == ["order_cancel:TimeoutError"]

    anyio.run(scenario)


def test_partial_cancel_requires_a_positive_quantity() -> None:
    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(
                _tracked(
                    state=OrderState.SUBMITTED,
                    quantity=14,
                    broker_order_id="0000117057",
                    broker_org_no="00950",
                ),
            )
        )
        broker = FakeBroker()

        result = await _submitter(store, broker).reduce_open_quantity(
            _ENVIRONMENT,
            "0000117057",
            0,
            _NOW,
        )

        assert result.accepted is False
        assert result.reason_code == "INVALID_QUANTITY"
        assert broker.cancels == []

    anyio.run(scenario)


def test_synchronize_reports_that_nothing_could_be_reconciled() -> None:
    """빈 응답은 성공이 아니다(ADR-0017 결정 3). 무작동을 '이상 없음'으로 보고하지 않는다."""

    async def scenario() -> None:
        store = FakeStore()
        broker = FakeBroker()

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _AFTER_HOURS)

        assert summary.verdict is AggregateVerdict.UNAVAILABLE

    anyio.run(scenario)


def test_synchronize_matches_the_broker_aggregate() -> None:
    async def scenario() -> None:
        store = FakeStore(daily_fill_totals_value=InternalDailyTotals(2, Decimal(498000)))
        broker = FakeBroker(totals=BrokerDailyTotals(2, Decimal(498000)))

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _AFTER_HOURS)

        assert summary.verdict is AggregateVerdict.MATCHED
        assert summary.paused is False

    anyio.run(scenario)


def test_a_mismatched_aggregate_pauses_automation() -> None:
    async def scenario() -> None:
        store = FakeStore(daily_fill_totals_value=InternalDailyTotals(2, Decimal(498000)))
        broker = FakeBroker(totals=BrokerDailyTotals(3, Decimal(747000)))

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _AFTER_HOURS)

        assert summary.verdict is AggregateVerdict.MISMATCHED
        assert summary.paused is True
        assert store.transitions == [
            (AutomationState.PAUSED, BlockCode.ACCOUNT_NOT_RECONCILED.value)
        ]

    anyio.run(scenario)


def test_a_matching_aggregate_expires_the_open_order_after_the_close() -> None:
    """집계 일치가 '미체결이 사실'이라는 관측 근거다(ADR-0017 결정 4)."""

    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(_tracked(state=OrderState.SUBMITTED, broker_order_id="0000009931"),),
            daily_fill_totals_value=InternalDailyTotals(0, Decimal(0)),
        )
        broker = FakeBroker(totals=BrokerDailyTotals(0, Decimal(0)))

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _AFTER_HOURS)

        assert summary.expired == ("a" * 32,)
        assert store.expired_orders == [(_ORDER_ID, "당일 체결 합계 수량 0 금액 0")]

    anyio.run(scenario)


def test_an_open_order_is_not_expired_during_the_session() -> None:
    """장중에는 아직 체결될 수 있다. 종결 판단을 하지 않는다."""

    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(_tracked(state=OrderState.SUBMITTED, broker_order_id="0000009931"),),
            daily_fill_totals_value=InternalDailyTotals(0, Decimal(0)),
        )
        broker = FakeBroker(totals=BrokerDailyTotals(0, Decimal(0)))

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _NOW)

        assert summary.expired == ()
        assert store.expired_orders == []

    anyio.run(scenario)


def test_an_unavailable_aggregate_never_expires_and_records_a_problem() -> None:
    async def scenario() -> None:
        store = FakeStore(
            open_orders_rows=(_tracked(state=OrderState.SUBMITTED, broker_order_id="0000009931"),),
        )
        broker = FakeBroker()

        summary = await _submitter(store, broker).synchronize(_ENVIRONMENT, _AFTER_HOURS)

        assert summary.expired == ()
        assert store.problems == [("0000009931", ReconcileProblem.DAILY_TOTALS_UNAVAILABLE)]
        assert summary.paused is True

    anyio.run(scenario)
