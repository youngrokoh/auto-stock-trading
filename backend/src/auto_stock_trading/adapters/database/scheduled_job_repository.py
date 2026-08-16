from typing import final
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.scheduled_job_rows import ScheduledJobRunRow
from auto_stock_trading.application.scheduled_jobs import (
    ScheduledJob,
    ScheduledJobClaim,
    ScheduledJobCompletion,
    ScheduledJobFailure,
    ScheduledJobLease,
    ScheduledJobLeaseLostError,
    ScheduledJobState,
)


@final
class PostgresScheduledJobRepository:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresScheduledJobRepository:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresScheduledJobRepository:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def claim(self, claim: ScheduledJobClaim) -> ScheduledJobLease | None:
        job = claim.job
        statement = (
            insert(ScheduledJobRunRow)
            .values(
                id=uuid4(),
                task_name=job.task_name,
                execution_key=job.execution_key,
                state=ScheduledJobState.RUNNING.value,
                owner_token=claim.owner_token,
                lease_expires_at=claim.lease_expires_at,
                attempt_count=1,
                started_at=claim.started_at,
                completed_at=None,
                error_code=None,
                created_at=claim.started_at,
                updated_at=claim.started_at,
            )
            .on_conflict_do_update(
                constraint="uq_scheduled_job_execution",
                set_={
                    "state": ScheduledJobState.RUNNING.value,
                    "owner_token": claim.owner_token,
                    "lease_expires_at": claim.lease_expires_at,
                    "attempt_count": ScheduledJobRunRow.attempt_count + 1,
                    "started_at": claim.started_at,
                    "completed_at": None,
                    "error_code": None,
                    "updated_at": claim.started_at,
                },
                where=or_(
                    ScheduledJobRunRow.state == ScheduledJobState.FAILED.value,
                    and_(
                        ScheduledJobRunRow.state == ScheduledJobState.RUNNING.value,
                        ScheduledJobRunRow.lease_expires_at <= claim.started_at,
                    ),
                ),
            )
            .returning(
                ScheduledJobRunRow.owner_token,
                ScheduledJobRunRow.attempt_count,
            )
        )
        async with self._sessions.begin() as session:
            row = (await session.execute(statement)).tuples().one_or_none()
        if row is None:
            return None
        owner_token, attempt_count = row
        return ScheduledJobLease(job, owner_token, attempt_count)

    async def complete(self, completion: ScheduledJobCompletion) -> None:
        lease = completion.lease
        statement = (
            update(ScheduledJobRunRow)
            .where(
                ScheduledJobRunRow.task_name == lease.job.task_name,
                ScheduledJobRunRow.execution_key == lease.job.execution_key,
                ScheduledJobRunRow.state == ScheduledJobState.RUNNING.value,
                ScheduledJobRunRow.owner_token == lease.owner_token,
            )
            .values(
                state=completion.state.value,
                completed_at=completion.completed_at,
                error_code=None,
                updated_at=completion.completed_at,
            )
            .returning(ScheduledJobRunRow.id)
        )
        async with self._sessions.begin() as session:
            row_id = await session.scalar(statement)
        if row_id is None:
            raise ScheduledJobLeaseLostError(lease.job)

    async def fail(self, failure: ScheduledJobFailure) -> None:
        lease = failure.lease
        statement = (
            update(ScheduledJobRunRow)
            .where(
                ScheduledJobRunRow.task_name == lease.job.task_name,
                ScheduledJobRunRow.execution_key == lease.job.execution_key,
                ScheduledJobRunRow.state == ScheduledJobState.RUNNING.value,
                ScheduledJobRunRow.owner_token == lease.owner_token,
            )
            .values(
                state=ScheduledJobState.FAILED.value,
                completed_at=failure.failed_at,
                error_code=failure.error_code,
                updated_at=failure.failed_at,
            )
            .returning(ScheduledJobRunRow.id)
        )
        async with self._sessions.begin() as session:
            row_id = await session.scalar(statement)
        if row_id is None:
            raise ScheduledJobLeaseLostError(lease.job)

    async def state(self, job: ScheduledJob) -> ScheduledJobState | None:
        statement = select(ScheduledJobRunRow.state).where(
            ScheduledJobRunRow.task_name == job.task_name,
            ScheduledJobRunRow.execution_key == job.execution_key,
        )
        async with self._sessions() as session:
            state = await session.scalar(statement)
        return ScheduledJobState(state) if state is not None else None

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
