from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import anyio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.scheduled_job_repository import (
    PostgresScheduledJobRepository,
)
from auto_stock_trading.application.scheduled_jobs import (
    ScheduledJob,
    ScheduledJobClaim,
    ScheduledJobCompletion,
    ScheduledJobFailure,
    ScheduledJobLeaseLostError,
    ScheduledJobState,
)
from auto_stock_trading.settings.runtime import Settings

type ScheduledJobScenario = Callable[
    [PostgresScheduledJobRepository, ScheduledJob],
    Awaitable[None],
]

_STARTED_AT = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)


def test_active_claim_prevents_a_duplicate_worker_from_acquiring() -> None:
    async def scenario(repository: PostgresScheduledJobRepository, job: ScheduledJob) -> None:
        # Given
        first_claim = _claim(job, UUID(int=1), _STARTED_AT)
        second_claim = _claim(job, UUID(int=2), _STARTED_AT + timedelta(minutes=1))

        # When
        first = await repository.claim(first_claim)
        second = await repository.claim(second_claim)

        # Then
        assert first is not None
        assert second is None
        assert await repository.state(job) is ScheduledJobState.RUNNING

    anyio.run(_run_scenario, scenario)


def test_failed_claim_can_be_retried_by_the_next_tick() -> None:
    async def scenario(repository: PostgresScheduledJobRepository, job: ScheduledJob) -> None:
        # Given
        first = await repository.claim(_claim(job, UUID(int=1), _STARTED_AT))
        assert first is not None
        await repository.fail(
            ScheduledJobFailure(first, _STARTED_AT + timedelta(minutes=1), "fixture_failure")
        )

        # When
        second = await repository.claim(
            _claim(job, UUID(int=2), _STARTED_AT + timedelta(minutes=10))
        )

        # Then
        assert second is not None
        assert second.attempt_count == 2

    anyio.run(_run_scenario, scenario)


def test_expired_claim_rejects_completion_from_the_previous_owner() -> None:
    async def scenario(repository: PostgresScheduledJobRepository, job: ScheduledJob) -> None:
        # Given
        first = await repository.claim(_claim(job, UUID(int=1), _STARTED_AT))
        assert first is not None
        second = await repository.claim(
            _claim(job, UUID(int=2), _STARTED_AT + timedelta(minutes=10))
        )
        assert second is not None

        # When / Then
        with pytest.raises(ScheduledJobLeaseLostError):
            await repository.complete(
                ScheduledJobCompletion(
                    first,
                    ScheduledJobState.SUCCEEDED,
                    _STARTED_AT + timedelta(minutes=11),
                )
            )

    anyio.run(_run_scenario, scenario)


def test_successful_claim_is_terminal_for_the_execution_key() -> None:
    async def scenario(repository: PostgresScheduledJobRepository, job: ScheduledJob) -> None:
        # Given
        first = await repository.claim(_claim(job, UUID(int=1), _STARTED_AT))
        assert first is not None
        await repository.complete(
            ScheduledJobCompletion(
                first,
                ScheduledJobState.SUCCEEDED,
                _STARTED_AT + timedelta(minutes=1),
            )
        )

        # When
        repeated = await repository.claim(
            _claim(job, UUID(int=2), _STARTED_AT + timedelta(minutes=10))
        )

        # Then
        assert repeated is None
        assert await repository.state(job) is ScheduledJobState.SUCCEEDED

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: ScheduledJobScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        repository = PostgresScheduledJobRepository.from_connection(connection)
        job = ScheduledJob("fixture-scheduled-job", f"fixture:{uuid4().hex}")
        try:
            await scenario(repository, job)
        finally:
            await repository.close()
            await transaction.rollback()
    await engine.dispose()


def _claim(job: ScheduledJob, owner_token: UUID, started_at: datetime) -> ScheduledJobClaim:
    return ScheduledJobClaim(
        job,
        owner_token,
        started_at,
        started_at + timedelta(minutes=9),
    )
