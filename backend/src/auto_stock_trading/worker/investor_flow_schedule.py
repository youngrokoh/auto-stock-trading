"""유니버스 수급 일일 예약(ADR-0006 패턴, 수급·공시 계약 §수급).

원천이 최근 약 30거래일만 주므로 이력은 첫 수집부터 축적되고 거른 구간은 되돌릴 수 없다. 그래서
매일 돌린다. 다만 30거래일 창이 여유이기도 하다 — 며칠 놓쳐도 다음 실행이 그 구간을 메운다.
한 달 넘게 거르면 그때부터 영구 공백이다.

`market_calendar_schedule`과 같은 규칙을 지킨다: 스케줄러는 자격증명을 받지 않고, 중복 방지는
프로세스 수가 아니라 PostgreSQL 실행 claim이 하며, 기본값은 꺼져 있다. 이 작업은 **읽기 전용
조회**이며 주문 경로와 무관하다.

서울 기준 당일 행은 저장하지 않으므로(장중 잠정치) 어느 거래일을 얻으려면 그 다음 날 돌려야
한다. 그래서 이른 아침에 실행한다. 거래일 판정은 하지 않는다 — 휴장일 실행은 같은 30거래일을
다시 관측하는 멱등 동작이고, 그 덕분에 놓친 날이 자동으로 복구된다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol, TypedDict
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from auto_stock_trading.adapters.brokers.kis_coordination import KisCoordinationError
from auto_stock_trading.adapters.brokers.kis_http import (
    KisConfigurationError,
    KisTransportError,
)
from auto_stock_trading.adapters.database.scheduled_job_repository import (
    PostgresScheduledJobRepository,
)
from auto_stock_trading.application.scheduled_jobs import (
    OperationFailed,
    OperationSucceeded,
    ScheduledJob,
    ScheduledJobExecutor,
    ScheduledJobOutcome,
    ScheduledJobRequest,
)
from auto_stock_trading.application.universe_investor_flows import FlowSweepResult
from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker import market_data
from auto_stock_trading.worker.broker import broker

# taskiq CLI가 `<module>:broker`로 지목할 수 있는 공개 이름이다.
__all__ = ["broker"]

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_TASK_NAME: Final = "scheduled_universe_investor_flows"
_EMPTY_UNIVERSE: Final = "empty_universe"


class CronSchedule(TypedDict):
    cron: str
    cron_offset: str
    schedule_id: str


def investor_flow_schedules(*, enabled: bool) -> list[CronSchedule]:
    """이른 아침 세 번 시도한다. 성공하면 claim이 나머지를 건너뛴다."""
    if not enabled:
        return []
    return [
        _cron("10 7 * * *", "universe-investor-flows-0710-kst"),
        _cron("10 8 * * *", "universe-investor-flows-0810-kst"),
        _cron("10 9 * * *", "universe-investor-flows-0910-kst"),
    ]


class FlowSweep(Protocol):
    async def __call__(self, now: datetime) -> FlowSweepResult: ...


@dataclass(frozen=True, slots=True)
class InvestorFlowSweepOperation:
    sweep: FlowSweep

    async def run(self) -> OperationSucceeded | OperationFailed:
        try:
            result = await self.sweep(datetime.now(UTC))
        except (
            KisConfigurationError,
            KisCoordinationError,
            KisTransportError,
            SQLAlchemyError,
        ) as error:
            return OperationFailed(datetime.now(UTC), type(error).__name__)
        completed_at = datetime.now(UTC)
        if result.failed > 0:
            # 수집된 종목은 이미 저장돼 있다. 실패로 남겨 같은 날 재시도가 남게 한다.
            return OperationFailed(completed_at, f"partial_failure:{result.failed}")
        if result.collected == 0:
            return OperationFailed(completed_at, _EMPTY_UNIVERSE)
        return OperationSucceeded(completed_at)


def investor_flow_job(started_at: datetime) -> ScheduledJob:
    """작업 키는 서울 날짜다. 하루에 한 번만 성공하고 그 뒤 시도는 건너뛴다."""
    local_date = started_at.astimezone(_SEOUL).date()
    return ScheduledJob(_TASK_NAME, f"universe-investor-flows:{local_date}")


async def run_scheduled_universe_investor_flows() -> str:
    settings = Settings()
    if not settings.investor_flow_schedule_enabled:
        return "disabled"
    return (await run_claimed_universe_investor_flows()).value


async def run_claimed_universe_investor_flows() -> ScheduledJobOutcome:
    settings = Settings()
    started_at = datetime.now(UTC)
    store = PostgresScheduledJobRepository.from_url(settings.database_url.get_secret_value())
    try:
        request = ScheduledJobRequest(investor_flow_job(started_at), started_at)
        return await ScheduledJobExecutor(store).execute(
            request,
            InvestorFlowSweepOperation(_sweep),
        )
    finally:
        await store.close()


async def _sweep(now: datetime) -> FlowSweepResult:
    _ = now
    collected, failed, failed_symbols = await market_data.collect_universe_investor_flows()
    return FlowSweepResult(collected=collected, failed=failed, failed_symbols=failed_symbols)


def _cron(cron: str, schedule_id: str) -> CronSchedule:
    return {"cron": cron, "cron_offset": "Asia/Seoul", "schedule_id": schedule_id}


_settings = Settings()
run_scheduled_universe_investor_flows_task = broker.task(
    task_name=_TASK_NAME,
    schedule=investor_flow_schedules(enabled=_settings.investor_flow_schedule_enabled),
)(run_scheduled_universe_investor_flows)

# 스케줄러 프로세스가 달력과 별개다. 중복 방지는 프로세스 수가 아니라 실행 claim이 한다(ADR-0006).
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
