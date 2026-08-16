from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, assert_never, final, override
from uuid import uuid4

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

_LEASE_DURATION = timedelta(minutes=9)


class ScheduledJobState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CONFLICT = "conflict"
    FAILED = "failed"


class ScheduledJobOutcome(StrEnum):
    SKIPPED = "skipped"
    SUCCEEDED = "succeeded"
    CONFLICT = "conflict"
    FAILED = "failed"


class ScheduledJobInvariant(StrEnum):
    AWARE_TIME = "scheduled job timestamps must include a timezone"
    COMPLETION_STATE = "scheduled job completion requires a terminal success state"


@final
@dataclass(frozen=True, slots=True)
class InvalidScheduledJobError(Exception):
    invariant: ScheduledJobInvariant

    @override
    def __str__(self) -> str:
        return self.invariant.value


@final
@dataclass(frozen=True, slots=True)
class ScheduledJobLeaseLostError(Exception):
    job: ScheduledJob

    @override
    def __str__(self) -> str:
        return f"scheduled job lease was lost for {self.job.task_name}:{self.job.execution_key}"


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    task_name: str
    execution_key: str


@dataclass(frozen=True, slots=True)
class ScheduledJobRequest:
    job: ScheduledJob
    started_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.started_at)


@dataclass(frozen=True, slots=True)
class ScheduledJobClaim:
    job: ScheduledJob
    owner_token: UUID
    started_at: datetime
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ScheduledJobLease:
    job: ScheduledJob
    owner_token: UUID
    attempt_count: int


@dataclass(frozen=True, slots=True)
class ScheduledJobCompletion:
    lease: ScheduledJobLease
    state: ScheduledJobState
    completed_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.completed_at)
        match self.state:
            case ScheduledJobState.SUCCEEDED | ScheduledJobState.CONFLICT:
                return
            case ScheduledJobState.RUNNING | ScheduledJobState.FAILED:
                raise InvalidScheduledJobError(ScheduledJobInvariant.COMPLETION_STATE)
            case _:
                assert_never(self.state)


@dataclass(frozen=True, slots=True)
class ScheduledJobFailure:
    lease: ScheduledJobLease
    failed_at: datetime
    error_code: str

    def __post_init__(self) -> None:
        _require_aware(self.failed_at)


@dataclass(frozen=True, slots=True)
class OperationSucceeded:
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class OperationConflict:
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class OperationFailed:
    failed_at: datetime
    error_code: str


type ScheduledOperationResult = OperationSucceeded | OperationConflict | OperationFailed


class ScheduledOperation(Protocol):
    async def run(self) -> ScheduledOperationResult: ...


class ScheduledJobStore(Protocol):
    async def claim(self, claim: ScheduledJobClaim) -> ScheduledJobLease | None: ...

    async def complete(self, completion: ScheduledJobCompletion) -> None: ...

    async def fail(self, failure: ScheduledJobFailure) -> None: ...

    async def state(self, job: ScheduledJob) -> ScheduledJobState | None: ...

    async def close(self) -> None: ...


@final
@dataclass(frozen=True, slots=True)
class ScheduledJobExecutor:
    store: ScheduledJobStore

    async def execute(
        self,
        request: ScheduledJobRequest,
        operation: ScheduledOperation,
    ) -> ScheduledJobOutcome:
        claim = ScheduledJobClaim(
            request.job,
            uuid4(),
            request.started_at,
            request.started_at + _LEASE_DURATION,
        )
        lease = await self.store.claim(claim)
        if lease is None:
            return ScheduledJobOutcome.SKIPPED
        result = await operation.run()
        match result:
            case OperationSucceeded(completed_at=completed_at):
                await self.store.complete(
                    ScheduledJobCompletion(
                        lease,
                        ScheduledJobState.SUCCEEDED,
                        completed_at,
                    )
                )
                return ScheduledJobOutcome.SUCCEEDED
            case OperationConflict(completed_at=completed_at):
                await self.store.complete(
                    ScheduledJobCompletion(
                        lease,
                        ScheduledJobState.CONFLICT,
                        completed_at,
                    )
                )
                return ScheduledJobOutcome.CONFLICT
            case OperationFailed(failed_at=failed_at, error_code=error_code):
                await self.store.fail(ScheduledJobFailure(lease, failed_at, error_code))
                return ScheduledJobOutcome.FAILED
            case _:
                assert_never(result)


def _require_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise InvalidScheduledJobError(ScheduledJobInvariant.AWARE_TIME)
