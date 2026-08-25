"""자동 스케줄 주문 제출(ADR-0015).

지키는 것은 세 가지다. 창 밖에서 돌지 않고, 계획이 막히면 제출하지 않으며, **차단은 사실로
남는다** — 사람이 없는 경로에서 조용한 실패가 가장 위험하다.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Final, final
from uuid import UUID
from zoneinfo import ZoneInfo

import anyio

from auto_stock_trading.application.scheduled_jobs import OperationFailed, OperationSucceeded
from auto_stock_trading.application.trading.submission import SubmissionResult
from auto_stock_trading.domain.orders.models import AutomationState
from auto_stock_trading.domain.orders.records import OrderPlanRecord
from auto_stock_trading.worker.execution.planning import SignalPlanOutcome
from auto_stock_trading.worker.execution.submission_schedule import (
    ScheduledSubmissionOperation,
    submission_job,
    submission_schedules,
)

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_ENVIRONMENT: Final = "paper"
_PLAN_ID: Final = UUID("00000000-0000-4000-8000-000000000901")
_NOW: Final = datetime(2026, 8, 25, 0, 20, tzinfo=UTC)


def test_no_schedule_when_disabled() -> None:
    assert submission_schedules(enabled=False) == []


def test_slots_stay_inside_the_order_window() -> None:
    """창 밖 슬롯을 만들지 않는다. 돌기만 하고 매번 차단되면 차단 이벤트가 의미를 잃는다."""
    slots = submission_schedules(enabled=True)

    minutes: list[time] = []
    for slot in slots:
        minute, hour, *_ = slot["cron"].split()
        minutes.append(time(int(hour), int(minute)))
    assert min(minutes) == time(9, 5)
    assert max(minutes) == time(15, 5)
    assert all(slot["cron_offset"] == "Asia/Seoul" for slot in slots)


def test_every_slot_has_a_distinct_identifier() -> None:
    slots = submission_schedules(enabled=True)

    identifiers = [slot["schedule_id"] for slot in slots]
    assert len(set(identifiers)) == len(identifiers)


def test_the_job_key_is_the_seoul_slot() -> None:
    """같은 슬롯은 한 번만 성공한다. 키가 날짜뿐이면 하루에 한 번밖에 못 돈다."""
    first = submission_job(datetime(2026, 8, 25, 0, 5, tzinfo=UTC))
    second = submission_job(datetime(2026, 8, 25, 0, 20, tzinfo=UTC))

    assert first.execution_key != second.execution_key
    assert first.execution_key == "order-submission:2026-08-25T09:05"


def _plan(status: str, block_code: str | None = None) -> OrderPlanRecord:
    return OrderPlanRecord(
        plan_id=_PLAN_ID,
        environment=_ENVIRONMENT,
        strategy_name="etf-allocation-momentum",
        strategy_version="1",
        parameters_json="{}",
        signal_date=date(2026, 8, 25),
        trading_date=date(2026, 8, 25),
        account_snapshot_id=None,
        nav_basis=Decimal(10_000_000),
        session_open_nav=Decimal(10_000_000),
        automation_state=AutomationState.RUNNING,
        status=status,
        block_code=block_code,
        planned_at=_NOW,
        orders=(),
        stored_orders=1,
    )


@final
@dataclass
class FakeStore:
    blocks: list[tuple[str, str]] = field(default_factory=list)

    async def record_schedule_block(
        self,
        environment: str,
        block_code: str,
        occurred_at: datetime,
    ) -> None:
        _ = occurred_at
        self.blocks.append((environment, block_code))

    async def close(self) -> None:
        return None


@final
@dataclass
class FakeOperation:
    """저장소만 가짜로 바꾼 실행. 나머지 규칙은 실제 코드가 돈다."""

    outcome: SignalPlanOutcome
    result: SubmissionResult
    store: FakeStore = field(default_factory=FakeStore)
    submitted: list[str] = field(default_factory=list)

    def build(self) -> ScheduledSubmissionOperation:
        return ScheduledSubmissionOperation(
            plan=self._plan,
            submit=self._submit,
            blocks=self.store,
            environment=_ENVIRONMENT,
        )

    async def _plan(self) -> SignalPlanOutcome:
        return self.outcome

    async def _submit(self, plan_id: str) -> SubmissionResult:
        self.submitted.append(plan_id)
        return self.result


def _outcome(plan: OrderPlanRecord | None) -> SignalPlanOutcome:
    return SignalPlanOutcome(plan=plan, signal=None, candidates=1, note="")


def _result(block_code: str | None = None, submitted: tuple[str, ...] = ()) -> SubmissionResult:
    return SubmissionResult(block_code=block_code, submitted=submitted, rejected=())


def test_a_successful_chain_plans_then_submits() -> None:
    async def scenario() -> None:
        fake = FakeOperation(_outcome(_plan("created")), _result(submitted=("a" * 32,)))

        result = await fake.build().run()

        assert isinstance(result, OperationSucceeded)
        assert fake.submitted == [str(_PLAN_ID)]
        assert fake.store.blocks == []

    anyio.run(scenario)


def test_a_blocked_plan_is_not_submitted_and_is_recorded() -> None:
    """계획이 막히면 제출하지 않는다. 그리고 차단 사실이 남아야 알림으로 나간다(결정 6)."""

    async def scenario() -> None:
        fake = FakeOperation(
            _outcome(_plan("blocked", "AUTOMATION_NOT_RUNNING")),
            _result(),
        )

        result = await fake.build().run()

        assert isinstance(result, OperationFailed)
        assert fake.submitted == []
        assert fake.store.blocks == [(_ENVIRONMENT, "AUTOMATION_NOT_RUNNING")]

    anyio.run(scenario)


def test_a_blocked_submission_is_recorded() -> None:
    async def scenario() -> None:
        fake = FakeOperation(
            _outcome(_plan("created")),
            _result(block_code="LISTENER_NOT_ATTACHED"),
        )

        result = await fake.build().run()

        assert isinstance(result, OperationFailed)
        assert fake.store.blocks == [(_ENVIRONMENT, "LISTENER_NOT_ATTACHED")]

    anyio.run(scenario)


def test_no_signal_is_not_a_block() -> None:
    """신호가 없는 것은 차단이 아니라 할 일이 없는 상태다. 차단 이벤트를 만들지 않는다."""

    async def scenario() -> None:
        fake = FakeOperation(_outcome(None), _result())

        result = await fake.build().run()

        assert isinstance(result, OperationFailed)
        assert result.error_code == "no_plan"
        assert fake.store.blocks == []
        assert fake.submitted == []

    anyio.run(scenario)


def test_a_transport_failure_does_not_escape() -> None:
    """예약 실행이 예외로 끝나면 claim이 실패로 남지 않고 다음 슬롯 판단이 흐려진다."""

    async def scenario() -> None:
        fake = FakeOperation(_outcome(_plan("created")), _result())

        async def failing(plan_id: str) -> SubmissionResult:
            _ = plan_id
            message = "timeout"
            raise TimeoutError(message)

        operation = ScheduledSubmissionOperation(
            plan=fake.build().plan,
            submit=failing,
            blocks=fake.store,
            environment=_ENVIRONMENT,
        )

        result = await operation.run()

        assert isinstance(result, OperationFailed)

    anyio.run(scenario)


def test_the_job_identifier_is_stable_for_the_same_slot() -> None:
    assert submission_job(_NOW).execution_key == submission_job(_NOW).execution_key
