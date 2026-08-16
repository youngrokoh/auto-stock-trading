from datetime import UTC, datetime
from typing import final
from uuid import UUID

import anyio
import anyio.lowlevel

from auto_stock_trading.application.scheduled_jobs import (
    OperationConflict,
    OperationFailed,
    OperationSucceeded,
    ScheduledJob,
    ScheduledJobClaim,
    ScheduledJobCompletion,
    ScheduledJobExecutor,
    ScheduledJobFailure,
    ScheduledJobLease,
    ScheduledJobOutcome,
    ScheduledJobRequest,
    ScheduledJobState,
)

_STARTED_AT = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 17, 20, 1, tzinfo=UTC)
_JOB = ScheduledJob("scheduled-calendar", "calendar:XKRX:2026-08-18")
_LEASE = ScheduledJobLease(_JOB, UUID(int=1), 1)


@final
class _FakeScheduledJobStore:
    def __init__(self, lease: ScheduledJobLease | None) -> None:
        self.lease = lease
        self.completion: ScheduledJobCompletion | None = None
        self.failure: ScheduledJobFailure | None = None

    async def claim(self, claim: ScheduledJobClaim) -> ScheduledJobLease | None:
        assert claim.job == _JOB
        return self.lease

    async def complete(self, completion: ScheduledJobCompletion) -> None:
        self.completion = completion

    async def fail(self, failure: ScheduledJobFailure) -> None:
        self.failure = failure

    async def state(self, job: ScheduledJob) -> ScheduledJobState | None:
        assert job == _JOB
        return None

    async def close(self) -> None:
        await anyio.lowlevel.checkpoint()


@final
class _FakeOperation:
    def __init__(
        self,
        result: OperationSucceeded | OperationConflict | OperationFailed,
    ) -> None:
        self.result = result
        self.calls = 0

    async def run(self) -> OperationSucceeded | OperationConflict | OperationFailed:
        self.calls += 1
        return self.result


def test_executor_skips_when_another_worker_owns_the_claim() -> None:
    # Given
    store = _FakeScheduledJobStore(None)
    operation = _FakeOperation(OperationSucceeded(_COMPLETED_AT))
    executor = ScheduledJobExecutor(store)

    # When
    outcome = anyio.run(executor.execute, ScheduledJobRequest(_JOB, _STARTED_AT), operation)

    # Then
    assert outcome is ScheduledJobOutcome.SKIPPED
    assert operation.calls == 0


def test_executor_records_a_successful_terminal_result() -> None:
    # Given
    store = _FakeScheduledJobStore(_LEASE)
    executor = ScheduledJobExecutor(store)

    # When
    outcome = anyio.run(
        executor.execute,
        ScheduledJobRequest(_JOB, _STARTED_AT),
        _FakeOperation(OperationSucceeded(_COMPLETED_AT)),
    )

    # Then
    assert outcome is ScheduledJobOutcome.SUCCEEDED
    assert store.completion == ScheduledJobCompletion(
        _LEASE,
        ScheduledJobState.SUCCEEDED,
        _COMPLETED_AT,
    )


def test_executor_records_a_conflict_as_a_terminal_result() -> None:
    # Given
    store = _FakeScheduledJobStore(_LEASE)
    executor = ScheduledJobExecutor(store)

    # When
    outcome = anyio.run(
        executor.execute,
        ScheduledJobRequest(_JOB, _STARTED_AT),
        _FakeOperation(OperationConflict(_COMPLETED_AT)),
    )

    # Then
    assert outcome is ScheduledJobOutcome.CONFLICT
    assert store.completion == ScheduledJobCompletion(
        _LEASE,
        ScheduledJobState.CONFLICT,
        _COMPLETED_AT,
    )


def test_executor_records_an_expected_operation_failure() -> None:
    # Given
    store = _FakeScheduledJobStore(_LEASE)
    executor = ScheduledJobExecutor(store)

    # When
    outcome = anyio.run(
        executor.execute,
        ScheduledJobRequest(_JOB, _STARTED_AT),
        _FakeOperation(OperationFailed(_COMPLETED_AT, "fixture_failure")),
    )

    # Then
    assert outcome is ScheduledJobOutcome.FAILED
    assert store.failure == ScheduledJobFailure(
        _LEASE,
        _COMPLETED_AT,
        "fixture_failure",
    )
