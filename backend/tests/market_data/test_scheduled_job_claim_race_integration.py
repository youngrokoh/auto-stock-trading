"""예약 작업 claim의 병렬 경합 검증(ADR-0006 중복 방지).

기존 통합 테스트는 두 claim 시도를 **순차로** 호출해 의미를 고정한다. 여기서는 두 커넥션이
**같은 순간** 같은 작업 키를 다투게 만들어, 원자성이 애플리케이션 순서가 아니라 DB 제약에서
나오는지 확인한다. ADR-0006이 "중복 방지는 프로세스 수가 아니라 실행 claim이 한다"고 정한
이상, 스케줄러가 둘로 늘어난 구성에서도 성립해야 한다.

claim은 `INSERT ... ON CONFLICT DO UPDATE ... WHERE`이므로 유일 제약이 승자를 하나로 만든다.
그 보장을 테스트로 고정하지 않으면, 나중에 조회 후 삽입 방식으로 바꿔도 순차 테스트는 계속
통과한다.
"""

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import anyio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.scheduled_job_repository import (
    PostgresScheduledJobRepository,
)
from auto_stock_trading.adapters.database.scheduled_job_rows import ScheduledJobRunRow
from auto_stock_trading.application.scheduled_jobs import (
    ScheduledJob,
    ScheduledJobClaim,
    ScheduledJobLease,
)
from auto_stock_trading.settings.runtime import Settings

_STARTED_AT: Final = datetime(2026, 8, 24, 0, 10, tzinfo=UTC)
_TASK_NAME: Final = "fixture-claim-race"
_CONTENDERS: Final = 6


def _claim(job: ScheduledJob, owner_token: UUID) -> ScheduledJobClaim:
    return ScheduledJobClaim(
        job,
        owner_token,
        _STARTED_AT,
        _STARTED_AT + timedelta(minutes=9),
    )


async def _cleanup(url: str, job: ScheduledJob) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            _ = await connection.execute(
                delete(ScheduledJobRunRow).where(
                    ScheduledJobRunRow.task_name == job.task_name,
                    ScheduledJobRunRow.execution_key == job.execution_key,
                )
            )
    finally:
        await engine.dispose()


def test_simultaneous_claims_on_one_key_grant_exactly_one_lease() -> None:
    """여섯 커넥션이 동시에 같은 작업 키를 claim하면 하나만 lease를 받는다.

    각 경합자가 자기 엔진(= 자기 트랜잭션)을 쓴다. 한 트랜잭션 안에서 두 번 호출하면 DB 수준
    경합이 성립하지 않아 아무것도 증명하지 못한다.
    """

    async def run() -> None:
        url = Settings().database_url.get_secret_value()
        job = ScheduledJob(_TASK_NAME, f"race:{uuid4().hex}")
        leases: list[ScheduledJobLease | None] = []
        # 모든 경합자가 같은 순간에 출발하도록 준비를 마친 뒤 문을 연다.
        gate = anyio.Event()

        async def contender(index: int) -> None:
            engine = create_async_engine(url)
            repository = PostgresScheduledJobRepository.from_url(url)
            try:
                await gate.wait()
                leases.append(await repository.claim(_claim(job, UUID(int=index + 1))))
            finally:
                await repository.close()
                await engine.dispose()

        try:
            async with anyio.create_task_group() as tasks:
                for index in range(_CONTENDERS):
                    _ = tasks.start_soon(contender, index)
                await anyio.sleep(0.2)
                gate.set()

            granted = [lease for lease in leases if lease is not None]
            assert len(leases) == _CONTENDERS
            assert len(granted) == 1, f"lease를 받은 경합자가 {len(granted)}명이다"
            assert granted[0].attempt_count == 1

            # 행도 하나뿐이어야 한다. 여럿이면 중복 실행이 이미 가능한 상태다.
            reader = create_async_engine(url)
            try:
                async with reader.connect() as connection:
                    rows = (
                        await connection.execute(
                            select(
                                ScheduledJobRunRow.owner_token,
                                ScheduledJobRunRow.attempt_count,
                            ).where(
                                ScheduledJobRunRow.task_name == job.task_name,
                                ScheduledJobRunRow.execution_key == job.execution_key,
                            )
                        )
                    ).all()
            finally:
                await reader.dispose()
            assert len(rows) == 1
            assert rows[0][0] == granted[0].owner_token
            assert rows[0][1] == 1
        finally:
            await _cleanup(url, job)

    anyio.run(run)
