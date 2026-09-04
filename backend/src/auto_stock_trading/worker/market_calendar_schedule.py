from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, TypedDict, assert_never
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from auto_stock_trading.adapters.brokers.kis_coordination import KisCoordinationError
from auto_stock_trading.adapters.brokers.kis_http import (
    KisConfigurationError,
    KisTransportError,
)
from auto_stock_trading.adapters.brokers.kis_mapping import KisApiError, KisContractError
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.scheduled_job_repository import (
    PostgresScheduledJobRepository,
)
from auto_stock_trading.adapters.exchanges.krx_market_calendar import (
    KrxContractError,
    KrxTransportError,
)
from auto_stock_trading.adapters.exchanges.krx_trading_hours_contracts import (
    KrxNoticeContractError,
)
from auto_stock_trading.application.market_calendar import (
    IncompleteCalendarRangeError,
    MissingPrimaryCalendarError,
    SameDayConfirmationRequiredError,
)
from auto_stock_trading.application.scheduled_jobs import (
    OperationConflict,
    OperationFailed,
    OperationSucceeded,
    ScheduledJob,
    ScheduledJobExecutor,
    ScheduledJobOutcome,
    ScheduledJobRequest,
    ScheduledJobState,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    ConfirmedVerification,
    ConflictingVerification,
    InvalidMarketCalendarError,
    MarketSessionType,
    PendingVerification,
)
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker import market_calendar
from auto_stock_trading.worker.broker import CALENDAR_CONFIRM_QUEUE, broker, create_broker

# 실전 확인은 전용 큐를 쓴다(ADR-0006). 실전 자격증명을 가진 워커가 기본 큐를 보면 모의 작업을
# 집어가므로 자격증명 분리가 무너진다. KRX 수집은 자격증명이 필요 없어 기본 큐에 남는다.
confirm_broker = create_broker(queue_name=CALENDAR_CONFIRM_QUEUE)

# taskiq CLI가 `<module>:<name>`으로 지목할 수 있는 공개 이름이다.
__all__ = ["broker", "confirm_broker"]

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_DECEMBER: Final = 12
_KRX_TASK_NAME: Final = "scheduled_krx_market_calendar"
_KIS_TASK_NAME: Final = "scheduled_kis_market_calendar_confirmation"


class CronSchedule(TypedDict):
    cron: str
    cron_offset: str
    schedule_id: str


def krx_calendar_schedules(*, enabled: bool) -> list[CronSchedule]:
    """이른 창에서 먼저 시도하고, 실패하면 확인 창과 같은 시간대까지 계속 재시도한다.

    작업 키가 하루 한 건이라 한 번 성공하면 나머지 시도는 claim이 건너뛴다. 연간 달력 수집은
    멱등이므로 늦은 재시도가 기존 사실을 흔들지 않는다.

    늦은 창이 필요한 이유(2026-09-04 실측): 이 시스템은 상시 서버가 아니라 사용자의 기계에서 돈다.
    새벽에 기계가 자면 도커 VM이 함께 멈춰 05~06시 슬롯이 통째로 비고, 깨어난 직후 밀린 슬롯 하나가
    네트워크가 올라오기 전에 나가 실패했다. **KIS 확인은 KRX 성공을 전제**하므로(`krx_pending`)
    가장 좁은 창이 달력 사슬 전체의 단일 실패점이 된다. 확인 쪽은 하루 종일 재시도하면서도 그날
    내내 `krx_pending`만 반환했다.

    ADR-0006의 순서 규칙은 그대로다. 늦게 수집해도 확인은 수집이 성공한 뒤에만 진행한다.
    """
    if not enabled:
        return []
    return [
        _cron("*/10 5 * * *", "krx-calendar-0500-0550-kst"),
        _cron("0,10,20 6 * * *", "krx-calendar-0600-0620-kst"),
        _cron("*/10 7-14 * * *", "krx-calendar-0700-1450-kst"),
    ]


def kis_calendar_schedules(*, enabled: bool) -> list[CronSchedule]:
    if not enabled:
        return []
    return [
        _cron("30,40,50 6 * * *", "kis-calendar-0630-0650-kst"),
        _cron("*/10 7-14 * * *", "kis-calendar-0700-1450-kst"),
        _cron("0,10,20 15 * * *", "kis-calendar-1500-1520-kst"),
    ]


def krx_schedule_years(started_at: datetime) -> tuple[int, ...]:
    local_time = started_at.astimezone(_SEOUL)
    if local_time.month == _DECEMBER:
        return (local_time.year, local_time.year + 1)
    return (local_time.year,)


@dataclass(frozen=True, slots=True)
class KrxCalendarOperation:
    year: int

    async def run(self) -> OperationSucceeded | OperationFailed:
        try:
            _ = await market_calendar.collect_krx_market_calendar(self.year)
        except (
            IncompleteCalendarRangeError,
            InvalidMarketCalendarError,
            KrxContractError,
            KrxNoticeContractError,
            KrxTransportError,
            SQLAlchemyError,
        ) as error:
            return OperationFailed(datetime.now(UTC), type(error).__name__)
        return OperationSucceeded(datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class KisCalendarOperation:
    key: CalendarSessionKey
    store: PostgresMarketCalendarRepository

    async def run(self) -> OperationSucceeded | OperationConflict | OperationFailed:
        try:
            _ = await market_calendar.confirm_today_market_calendar()
            record = await self.store.session(self.key)
        except (
            InvalidMarketCalendarError,
            KisApiError,
            KisConfigurationError,
            KisContractError,
            KisCoordinationError,
            KisTransportError,
            MissingPrimaryCalendarError,
            SameDayConfirmationRequiredError,
            SQLAlchemyError,
        ) as error:
            return OperationFailed(datetime.now(UTC), type(error).__name__)
        if record is None:
            return OperationFailed(datetime.now(UTC), "MissingConfirmedCalendar")
        completed_at = datetime.now(UTC)
        match record.verification:
            case ConfirmedVerification():
                return OperationSucceeded(completed_at)
            case ConflictingVerification():
                return OperationConflict(completed_at)
            case PendingVerification():
                return OperationFailed(completed_at, "PendingAfterConfirmation")
            case _:
                assert_never(record.verification)


async def run_scheduled_krx_market_calendar() -> tuple[str, ...]:
    started_at = datetime.now(UTC)
    outcomes: list[str] = []
    for year in krx_schedule_years(started_at):
        outcome = await run_claimed_krx_market_calendar(year, started_at)
        outcomes.append(f"{year}:{outcome.value}")
    return tuple(outcomes)


async def run_claimed_krx_market_calendar(
    year: int,
    started_at: datetime | None = None,
) -> ScheduledJobOutcome:
    settings = Settings()
    actual_started_at = started_at or datetime.now(UTC)
    store = PostgresScheduledJobRepository.from_url(settings.database_url.get_secret_value())
    try:
        request = ScheduledJobRequest(_krx_job(year, actual_started_at), actual_started_at)
        return await ScheduledJobExecutor(store).execute(request, KrxCalendarOperation(year))
    finally:
        await store.close()


async def run_scheduled_kis_market_calendar_confirmation() -> str:
    settings = Settings()
    if (
        settings.kis_environment is not KisEnvironment.LIVE
        or not settings.kis_calendar_schedule_enabled
    ):
        return "disabled"
    return await run_claimed_kis_market_calendar_confirmation()


async def run_claimed_kis_market_calendar_confirmation() -> str:
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.LIVE:
        return "disabled"
    started_at = datetime.now(UTC)
    local_date = started_at.astimezone(_SEOUL).date()
    key = CalendarSessionKey("KR", "XKRX", local_date, MarketSessionType.REGULAR)
    job_store = PostgresScheduledJobRepository.from_url(settings.database_url.get_secret_value())
    calendar_store = PostgresMarketCalendarRepository.from_url(
        settings.database_url.get_secret_value()
    )
    try:
        krx_state = await job_store.state(_krx_job(local_date.year, started_at))
        if krx_state is not ScheduledJobState.SUCCEEDED:
            return "krx_pending"
        current = await calendar_store.session(key)
        if current is None:
            return "missing"
        match current.verification:
            case ConfirmedVerification():
                return "confirmed"
            case ConflictingVerification():
                return "conflict"
            case PendingVerification():
                request = ScheduledJobRequest(
                    ScheduledJob(
                        _KIS_TASK_NAME,
                        f"kis-calendar:XKRX:{local_date}:v{current.version}",
                    ),
                    started_at,
                )
                outcome = await ScheduledJobExecutor(job_store).execute(
                    request,
                    KisCalendarOperation(key, calendar_store),
                )
                return outcome.value
            case _:
                assert_never(current.verification)
    finally:
        await calendar_store.close()
        await job_store.close()


def _krx_job(year: int, started_at: datetime) -> ScheduledJob:
    local_date = started_at.astimezone(_SEOUL).date()
    return ScheduledJob(_KRX_TASK_NAME, f"krx-calendar:XKRX:{year}:{local_date}")


def _cron(cron: str, schedule_id: str) -> CronSchedule:
    return {"cron": cron, "cron_offset": "Asia/Seoul", "schedule_id": schedule_id}


_settings = Settings()
run_scheduled_krx_market_calendar_task = broker.task(
    task_name=_KRX_TASK_NAME,
    schedule=krx_calendar_schedules(enabled=_settings.krx_calendar_schedule_enabled),
)(run_scheduled_krx_market_calendar)
run_scheduled_kis_market_calendar_confirmation_task = confirm_broker.task(
    task_name=_KIS_TASK_NAME,
    schedule=kis_calendar_schedules(
        enabled=_settings.kis_calendar_schedule_enabled
        and _settings.kis_environment is KisEnvironment.LIVE
    ),
)(run_scheduled_kis_market_calendar_confirmation)
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
# 확인 작업은 자기 브로커로 발행한다. 스케줄러는 자격증명을 갖지 않는다(ADR-0006).
confirm_scheduler = TaskiqScheduler(
    confirm_broker,
    sources=[LabelScheduleSource(confirm_broker)],
)
