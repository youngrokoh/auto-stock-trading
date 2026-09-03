"""ETF NAV 주간 예약(ADR-0021 결정 4의 일부, ETF 탐색 데이터 계약 §분류 사실).

**재수집 주기가 규칙의 일부다.** ETF의 업종 키는 30일보다 오래된 관측을 미분류로 읽는다. 수집이
멈추면 fail-closed로 안전하게 막히지만, 그 결과 ETF 배분 전략이 다시 아무것도 사지 못한다. 이
예약이 그 상태를 막는다.

`investor_flow_schedule`과 같은 규칙을 지킨다: 스케줄러는 자격증명을 받지 않고, 중복 방지는
프로세스 수가 아니라 PostgreSQL 실행 claim이 하며, 기본값은 꺼져 있다. 이 작업은 **읽기 전용
조회**이며 주문 경로와 무관하다.

주 1회인 이유는 두 가지다. 전수 수집이 모의 호출 한도에서 약 21분이라 자주 돌릴 것이 아니고,
추종 지수는 거의 바뀌지 않는다. 30일 창에 주 1회면 만료 전에 네 번의 기회가 있다.
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
from auto_stock_trading.application.etf import EtfNavSweepResult
from auto_stock_trading.application.scheduled_jobs import (
    OperationFailed,
    OperationSucceeded,
    ScheduledJob,
    ScheduledJobExecutor,
    ScheduledJobOutcome,
    ScheduledJobRequest,
)
from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker import market_data
from auto_stock_trading.worker.broker import broker

# taskiq CLI가 `<module>:broker`로 지목할 수 있는 공개 이름이다.
__all__ = ["broker"]

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_TASK_NAME: Final = "scheduled_etf_nav"
_EMPTY_SWEEP: Final = "empty_sweep"


class CronSchedule(TypedDict):
    cron: str
    cron_offset: str
    schedule_id: str


def etf_nav_schedules(*, enabled: bool) -> list[CronSchedule]:
    """수요일 장 마감 뒤 세 번 시도한다. 성공하면 claim이 나머지를 건너뛴다.

    장중을 피하는 이유는 21분 동안 호출 한도를 쓰기 때문이다 — 주문 계획이 기준가를 새로 받아야
    하는 시간대와 겹치면 안 된다. 수요일이 휴장일이어도 시세 응답은 직전 종가 기준으로 오고, 분류에
    쓰는 지수 이름은 그래도 정확하다.
    """
    if not enabled:
        return []
    return [
        _cron("30 16 * * 3", "etf-nav-1630-kst"),
        _cron("30 17 * * 3", "etf-nav-1730-kst"),
        _cron("30 18 * * 3", "etf-nav-1830-kst"),
    ]


class NavSweep(Protocol):
    async def __call__(self, now: datetime) -> EtfNavSweepResult: ...


@dataclass(frozen=True, slots=True)
class EtfNavSweepOperation:
    sweep: NavSweep

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
        if result.collected == 0:
            # 한 종목도 못 얻었다면 인증·네트워크 문제다. 같은 날 다시 시도할 값어치가 있다.
            return OperationFailed(completed_at, _EMPTY_SWEEP)
        # 일부 종목 실패는 재시도를 강제하지 않는다(수급 예약과 다른 판단). 실패한 종목은 이전
        # 분류 사실을 그대로 유지하고 그 사실은 30일간 유효하며, 다음 주 수집이 어차피 전 종목을
        # 다시 관측한다. 21분짜리 전수 수집을 몇 종목 때문에 다시 도는 것은 호출 한도만 쓴다.
        return OperationSucceeded(completed_at)


def etf_nav_job(started_at: datetime) -> ScheduledJob:
    """작업 키는 서울 날짜다. 같은 날 재시도는 한 번만 성공한다."""
    local_date = started_at.astimezone(_SEOUL).date()
    return ScheduledJob(_TASK_NAME, f"etf-nav:{local_date}")


async def run_scheduled_etf_nav() -> str:
    settings = Settings()
    if not settings.etf_nav_schedule_enabled:
        return "disabled"
    return (await run_claimed_etf_nav()).value


async def run_claimed_etf_nav() -> ScheduledJobOutcome:
    settings = Settings()
    started_at = datetime.now(UTC)
    store = PostgresScheduledJobRepository.from_url(settings.database_url.get_secret_value())
    try:
        request = ScheduledJobRequest(etf_nav_job(started_at), started_at)
        return await ScheduledJobExecutor(store).execute(request, EtfNavSweepOperation(_sweep))
    finally:
        await store.close()


async def _sweep(now: datetime) -> EtfNavSweepResult:
    _ = now
    collected, failed = await market_data.collect_etf_nav()
    return EtfNavSweepResult(collected=collected, failed=failed)


def _cron(cron: str, schedule_id: str) -> CronSchedule:
    return {"cron": cron, "cron_offset": "Asia/Seoul", "schedule_id": schedule_id}


_settings = Settings()
run_scheduled_etf_nav_task = broker.task(
    task_name=_TASK_NAME,
    schedule=etf_nav_schedules(enabled=_settings.etf_nav_schedule_enabled),
)(run_scheduled_etf_nav)

# 스케줄러 프로세스가 다른 예약과 별개다. 중복 방지는 프로세스 수가 아니라 실행 claim이 한다.
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
