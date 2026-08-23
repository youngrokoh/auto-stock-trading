"""수급 일일 예약(ADR-0006 패턴). 중복 방지는 PostgreSQL 실행 claim이 한다.

여기서 고정하는 것은 세 가지다: 기본은 꺼져 있다, 부분 실패는 실패로 보고해 다음 시도가 남는다,
작업 키가 서울 날짜라 하루에 한 번만 성공한다.
"""

from datetime import UTC, datetime

import anyio

from auto_stock_trading.application.scheduled_jobs import OperationFailed, OperationSucceeded
from auto_stock_trading.application.universe_investor_flows import FlowSweepResult
from auto_stock_trading.worker.investor_flow_schedule import (
    InvestorFlowSweepOperation,
    investor_flow_job,
    investor_flow_schedules,
)

_STARTED = datetime(2026, 8, 23, 22, 5, tzinfo=UTC)


def test_the_schedule_is_empty_when_disabled() -> None:
    assert investor_flow_schedules(enabled=False) == []


def test_the_schedule_runs_on_seoul_time_with_retries() -> None:
    schedules = investor_flow_schedules(enabled=True)

    assert schedules != []
    assert all(entry["cron_offset"] == "Asia/Seoul" for entry in schedules)
    # 원천이 최근 약 30거래일을 주므로 하루 놓쳐도 다음 실행이 메운다. 재시도는 같은 날 안에서다.
    assert len({entry["schedule_id"] for entry in schedules}) == len(schedules)


def test_the_job_key_is_the_seoul_date_so_it_succeeds_once_a_day() -> None:
    # 2026-08-23 22:05 UTC = 2026-08-24 07:05 KST
    job = investor_flow_job(_STARTED)

    assert job.execution_key == "universe-investor-flows:2026-08-24"


def test_a_clean_sweep_succeeds() -> None:
    async def sweep(now: datetime) -> FlowSweepResult:
        _ = now
        return FlowSweepResult(collected=200, failed=0, failed_symbols=())

    outcome = anyio.run(InvestorFlowSweepOperation(sweep).run)

    assert isinstance(outcome, OperationSucceeded)


def test_a_partial_failure_is_reported_as_failed_so_a_retry_remains() -> None:
    """수집된 종목은 이미 저장돼 있다. 실패로 남겨야 남은 종목을 같은 날 다시 시도한다."""

    async def sweep(now: datetime) -> FlowSweepResult:
        _ = now
        return FlowSweepResult(
            collected=198,
            failed=2,
            failed_symbols=("000880", "005930"),
        )

    outcome = anyio.run(InvestorFlowSweepOperation(sweep).run)

    assert isinstance(outcome, OperationFailed)
    assert outcome.error_code == "partial_failure:2"


def test_collecting_nothing_is_a_failure_not_a_silent_success() -> None:
    async def sweep(now: datetime) -> FlowSweepResult:
        _ = now
        return FlowSweepResult(collected=0, failed=0, failed_symbols=())

    outcome = anyio.run(InvestorFlowSweepOperation(sweep).run)

    assert isinstance(outcome, OperationFailed)
    assert outcome.error_code == "empty_universe"
