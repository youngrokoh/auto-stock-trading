"""ETF NAV 주간 예약(ADR-0021 결정 4). 분류 신선도를 지키는 것이 목적이다.

여기서 고정하는 것: 기본은 꺼져 있다, 주 1회 서울 시각으로 돈다, 아무것도 수집하지 못하면
실패로 남아 재시도가 있다, 그리고 **일부 종목 실패는 재시도를 강제하지 않는다** — 수급 예약과
다른 판단이라 명시적으로 고정한다.
"""

from datetime import UTC, datetime

import anyio

from auto_stock_trading.application.etf import EtfNavSweepResult
from auto_stock_trading.application.scheduled_jobs import OperationFailed, OperationSucceeded
from auto_stock_trading.worker.etf_nav_schedule import (
    EtfNavSweepOperation,
    etf_nav_job,
    etf_nav_schedules,
)

_STARTED = datetime(2026, 9, 2, 7, 30, tzinfo=UTC)


def test_the_schedule_is_empty_when_disabled() -> None:
    assert etf_nav_schedules(enabled=False) == []


def test_the_schedule_runs_weekly_on_seoul_time_after_the_close() -> None:
    schedules = etf_nav_schedules(enabled=True)

    assert schedules != []
    assert all(entry["cron_offset"] == "Asia/Seoul" for entry in schedules)
    assert len({entry["schedule_id"] for entry in schedules}) == len(schedules)
    # 전수 수집이 약 21분이라 장중에 돌리지 않는다. 요일을 고정해 주 1회가 되게 한다.
    for entry in schedules:
        minute, hour, _day, _month, weekday = entry["cron"].split()
        assert weekday != "*"
        assert int(hour) >= 16
        assert minute.isdigit()


def test_the_job_key_is_the_seoul_date_so_retries_collapse() -> None:
    # 2026-09-02 07:30 UTC = 2026-09-02 16:30 KST
    assert etf_nav_job(_STARTED).execution_key == "etf-nav:2026-09-02"


def test_a_clean_sweep_succeeds() -> None:
    async def sweep(now: datetime) -> EtfNavSweepResult:
        _ = now
        return EtfNavSweepResult(collected=1163, failed=0)

    assert isinstance(anyio.run(EtfNavSweepOperation(sweep).run), OperationSucceeded)


def test_a_few_symbol_failures_do_not_force_a_retry() -> None:
    """수급 예약과 다른 판단이다.

    실패한 종목은 이전 분류 사실을 그대로 유지하고 그 사실은 30일간 유효하며, 다음 주 수집이
    어차피 전 종목을 다시 관측한다. 21분짜리 전수 수집을 몇 종목 때문에 같은 날 다시 돌리는 것은
    얻는 것 없이 호출 한도만 쓴다.
    """

    async def sweep(now: datetime) -> EtfNavSweepResult:
        _ = now
        return EtfNavSweepResult(collected=1160, failed=3)

    assert isinstance(anyio.run(EtfNavSweepOperation(sweep).run), OperationSucceeded)


def test_collecting_nothing_is_a_failure_so_a_retry_remains() -> None:
    """한 종목도 못 얻었다면 인증·네트워크 문제다. 그건 같은 날 다시 시도할 값어치가 있다."""

    async def sweep(now: datetime) -> EtfNavSweepResult:
        _ = now
        return EtfNavSweepResult(collected=0, failed=1163)

    outcome = anyio.run(EtfNavSweepOperation(sweep).run)

    assert isinstance(outcome, OperationFailed)
    assert outcome.error_code == "empty_sweep"
