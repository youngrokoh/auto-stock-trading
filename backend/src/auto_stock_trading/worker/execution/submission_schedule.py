"""자동 스케줄 주문 제출(ADR-0015). 계획과 제출을 **한 작업**으로 묶는다.

독립 제출 cron을 만들지 않는 이유는 실측이다: 10초 기준가 규칙은 계획·정정 시점에만 강제되고
제출 경로에는 없으며, 제출 대상은 거래일 단위로만 걸러진다. 계획과 제출이 벌어지면 지정가가 오래된
기준가에 근거한다. 계획이 방금 만든 주문만 제출하면 그 간격이 초 단위로 유지된다(결정 1).

ADR-0006의 예약 규칙을 그대로 지킨다: 서울 기준 cron, PostgreSQL 실행 claim으로 중복 방지,
scheduler는 자격증명을 갖지 않는다. 자동매매를 켜는 것은 사람이며 이 작업은 상태를 올리지 않는다
(결정 3).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol, TypedDict
from zoneinfo import ZoneInfo

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from auto_stock_trading.adapters.database.scheduled_job_repository import (
    PostgresScheduledJobRepository,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.scheduled_jobs import (
    OperationFailed,
    OperationSucceeded,
    ScheduledJob,
    ScheduledJobExecutor,
    ScheduledJobOutcome,
    ScheduledJobRequest,
)
from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker.broker import ORDER_SUBMISSION_QUEUE, create_broker
from auto_stock_trading.worker.execution import planning, submission

if TYPE_CHECKING:
    from auto_stock_trading.application.trading.submission import SubmissionResult

# 주문 제출 전용 큐(브로커 모듈 참조). 기본 워커와 같은 큐를 보면 슬롯이 그 워커에 잡혀 사라진다.
broker = create_broker(queue_name=ORDER_SUBMISSION_QUEUE)

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_TASK_NAME: Final = "scheduled_order_submission"
_NO_PLAN: Final = "no_plan"
_BLOCKED: Final = "blocked"
# 주문 허용시간 09:05~15:15 KST. 창 밖 슬롯은 만들지 않는다.
_OPEN_HOUR: Final = 9
_FIRST_MINUTE: Final = 5
_SLOT_MINUTES: Final = (5, 20, 35, 50)


class CronSchedule(TypedDict):
    cron: str
    cron_offset: str
    schedule_id: str


def submission_schedules(*, enabled: bool) -> list[CronSchedule]:
    """주문 허용시간(09:05~15:15 KST) 안에서 15분마다(결정 2).

    창 밖 슬롯을 만들지 않는다. 제출 게이트가 다시 검사하지만, 애초에 돌지 않는 것이 낫다 —
    돌기만 하고 매번 차단되면 차단 이벤트가 의미를 잃는다.
    """
    if not enabled:
        return []
    slots = [
        _cron(f"{minute} {hour} * * 1-5", f"order-submission-{hour:02d}{minute:02d}-kst")
        for hour in range(_OPEN_HOUR, 15)
        for minute in _SLOT_MINUTES
        if not (hour == _OPEN_HOUR and minute < _FIRST_MINUTE)
    ]
    slots.append(_cron("5 15 * * 1-5", "order-submission-1505-kst"))
    return slots


class PlanRunner(Protocol):
    async def __call__(self) -> planning.SignalPlanOutcome: ...


class SubmitRunner(Protocol):
    async def __call__(self, plan_id: str) -> SubmissionResult: ...


class BlockRecorder(Protocol):
    """차단을 사실로 남기는 최소 표면. 실행이 저장소를 직접 만들지 않는다."""

    async def record_schedule_block(
        self,
        environment: str,
        block_code: str,
        occurred_at: datetime,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ScheduledSubmissionOperation:
    """계획 → 제출을 한 실행 안에서 수행한다. 차단은 사실로 남긴다(결정 6)."""

    plan: PlanRunner
    submit: SubmitRunner
    blocks: BlockRecorder
    environment: str

    async def run(self) -> OperationSucceeded | OperationFailed:
        # `ScheduledJobExecutor`는 `run()`을 try 없이 호출한다. 예외가 새어 나가면 claim이 결과 없이
        # 남아 lease 만료까지 감사 기록이 빈다 — 주문 경로에서는 그 공백을 허용하지 않는다.
        try:
            outcome = await self.plan()
        except Exception as error:  # noqa: BLE001 — 위 주석 참조
            return OperationFailed(datetime.now(UTC), type(error).__name__)
        if outcome.plan is None:
            # 신호가 없거나 후보가 없다. 차단이 아니라 할 일이 없는 상태다.
            return OperationFailed(datetime.now(UTC), _NO_PLAN)
        if outcome.plan.status == _BLOCKED:
            await self._record_block(outcome.plan.block_code or _BLOCKED)
            return OperationFailed(datetime.now(UTC), f"{_BLOCKED}:{outcome.plan.block_code}")
        try:
            result = await self.submit(str(outcome.plan.plan_id))
        except Exception as error:  # noqa: BLE001 — 같은 이유로 claim에 결과를 남긴다
            return OperationFailed(datetime.now(UTC), type(error).__name__)
        if result.block_code is not None:
            await self._record_block(result.block_code)
            return OperationFailed(datetime.now(UTC), f"{_BLOCKED}:{result.block_code}")
        return OperationSucceeded(datetime.now(UTC))

    async def _record_block(self, block_code: str) -> None:
        """차단을 저장해 알림 경로가 읽게 한다. 저장하지 않으면 조용히 지나간다."""
        await self.blocks.record_schedule_block(self.environment, block_code, datetime.now(UTC))


def submission_job(started_at: datetime) -> ScheduledJob:
    """작업 키는 서울 시각의 슬롯이다. 같은 슬롯은 한 번만 성공한다."""
    local = started_at.astimezone(_SEOUL)
    return ScheduledJob(_TASK_NAME, f"order-submission:{local:%Y-%m-%dT%H:%M}")


async def run_scheduled_order_submission() -> str:
    settings = Settings()
    if not settings.order_submission_schedule_enabled:
        return "disabled"
    return (await run_claimed_order_submission()).value


async def run_claimed_order_submission() -> ScheduledJobOutcome:
    settings = Settings()
    started_at = datetime.now(UTC)
    database_url = settings.database_url.get_secret_value()
    store = PostgresScheduledJobRepository.from_url(database_url)
    blocks = PostgresTradingStore.from_url(database_url)
    try:
        request = ScheduledJobRequest(submission_job(started_at), started_at)
        return await ScheduledJobExecutor(store).execute(
            request,
            ScheduledSubmissionOperation(
                plan=planning.plan_from_signal_record,
                submit=_submit,
                blocks=blocks,
                environment=settings.kis_environment.value,
            ),
        )
    finally:
        await blocks.close()
        await store.close()


async def _submit(plan_id: str) -> SubmissionResult:
    return await submission.submit_plan(plan_id)


def _cron(cron: str, schedule_id: str) -> CronSchedule:
    return {"cron": cron, "cron_offset": "Asia/Seoul", "schedule_id": schedule_id}


_settings = Settings()
run_scheduled_order_submission_task = broker.task(
    task_name=_TASK_NAME,
    schedule=submission_schedules(enabled=_settings.order_submission_schedule_enabled),
)(run_scheduled_order_submission)

# 중복 방지는 프로세스 수가 아니라 실행 claim이 한다(ADR-0006).
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
