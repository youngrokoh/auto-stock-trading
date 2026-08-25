"""사람이 확인한 재조정 문제 해소 저장소(ADR-0018). `trading_store.py`가 검토 한계를 넘어 분리한다.

읽는 것은 판정에 필요한 사실뿐이다 — 그 주문번호의 문제 건수, 우리 기록의 주문 상태(없으면 `None`),
이미 해소했는지. 판정은 순수 함수가 하고 이 모듈은 사실만 옮긴다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    OrderPlanRow,
    OrderRow,
    ReconcileResolutionRow,
)
from auto_stock_trading.domain.orders.models import OrderState
from auto_stock_trading.domain.orders.reconciliation import ResolutionTarget

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from auto_stock_trading.domain.orders.reconciliation import ResolutionOutcome

_RECONCILE_PROBLEM: Final = "reconcile_problem"
_RESOLVED_EVENT: Final = "reconcile_resolved"
_REASON: Final = "HUMAN_RESOLVED"
_DETAIL_LIMIT: Final = 500


def _detail(outcome: ResolutionOutcome) -> str:
    """감사 이벤트 본문. ADR-0010의 사람 확인과 같은 형식을 쓴다."""
    return f"operator={outcome.operator} evidence={outcome.evidence}"[:_DETAIL_LIMIT]


@final
class PostgresReconcileStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresReconcileStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresReconcileStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def target(self, environment: str, broker_order_id: str) -> ResolutionTarget:
        problems = (
            select(func.count())
            .select_from(AutomationEventRow)
            .where(
                AutomationEventRow.environment == environment,
                AutomationEventRow.event_type == _RECONCILE_PROBLEM,
                AutomationEventRow.detail == broker_order_id,
            )
        )
        state = (
            select(OrderRow.state)
            .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
            .where(
                OrderPlanRow.environment == environment,
                OrderRow.broker_order_id == broker_order_id,
            )
            .limit(1)
        )
        existing = select(ReconcileResolutionRow.id).where(
            ReconcileResolutionRow.environment == environment,
            ReconcileResolutionRow.broker_order_id == broker_order_id,
        )
        async with self._sessions() as session:
            count = await session.scalar(problems) or 0
            stored_state = await session.scalar(state)
            resolved = await session.scalar(existing)
        return ResolutionTarget(
            broker_order_id=broker_order_id,
            problem_count=count,
            order_state=None if stored_state is None else OrderState(stored_state),
            resolved=resolved is not None,
        )

    async def save(
        self,
        environment: str,
        outcome: ResolutionOutcome,
        resolved_at: datetime,
    ) -> None:
        """해소 사실과 감사 이벤트를 한 트랜잭션에 남긴다. 문제 이벤트는 고치지 않는다."""
        async with self._sessions.begin() as session:
            session.add(
                ReconcileResolutionRow(
                    id=uuid4(),
                    environment=environment,
                    broker_order_id=outcome.broker_order_id,
                    operator=outcome.operator,
                    evidence=outcome.evidence,
                    problem_count=outcome.problem_count,
                    resolved_at=resolved_at,
                )
            )
            session.add(
                AutomationEventRow(
                    id=uuid4(),
                    environment=environment,
                    event_type=_RESOLVED_EVENT,
                    previous_state=None,
                    state=None,
                    reason_code=_REASON,
                    detail=_detail(outcome),
                    occurred_at=resolved_at,
                )
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
