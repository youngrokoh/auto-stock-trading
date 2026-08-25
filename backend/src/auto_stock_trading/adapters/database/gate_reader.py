"""실전 전환 게이트 측정값 읽기. 저장된 사실만 센다.

없는 값은 여기서 만들지 않는다 — 가용성·시나리오·보고서처럼 원천이 없는 조건은 도메인이
'판정 불가'로 표시하며 이 어댑터는 아예 세지 않는다.
"""

from __future__ import annotations

from typing import final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.strategy_backtest_rows import LiveSignalRow
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    OrderPlanRow,
    OrderRow,
)
from auto_stock_trading.domain.gate.readiness import GateMeasurements
from auto_stock_trading.domain.orders.models import OrderState

_FILLED_STATES = (OrderState.FILLED.value, OrderState.PARTIALLY_FILLED.value)
_INCIDENT_TYPES = ("api_failure", "reconcile_problem")
_RECONCILE_PROBLEM = "reconcile_problem"
# 정책 §4의 '최근 20거래일'. 거래일 달력 없이 세면 휴장일이 섞이므로 계획이 있던 거래일로 센다.
_INCIDENT_WINDOW_DAYS = 20


@final
class PostgresGateReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresGateReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresGateReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def measurements(self, environment: str) -> GateMeasurements:
        trading_days = select(func.count(func.distinct(OrderPlanRow.trading_date))).where(
            OrderPlanRow.environment == environment
        )
        cycles = select(func.count(func.distinct(LiveSignalRow.rebalance_date))).where(
            LiveSignalRow.environment == environment
        )
        filled = (
            select(func.count())
            .select_from(OrderRow)
            .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
            .where(
                OrderPlanRow.environment == environment,
                OrderRow.state.in_(_FILLED_STATES),
            )
        )
        unreconciled = (
            select(func.count())
            .select_from(AutomationEventRow)
            .where(
                AutomationEventRow.environment == environment,
                AutomationEventRow.event_type == _RECONCILE_PROBLEM,
            )
        )
        async with self._sessions() as session:
            recent_days = (
                await session.scalars(
                    select(OrderPlanRow.trading_date)
                    .where(OrderPlanRow.environment == environment)
                    .distinct()
                    .order_by(OrderPlanRow.trading_date.desc())
                    .limit(_INCIDENT_WINDOW_DAYS)
                )
            ).all()
            incidents = 0
            if recent_days:
                incidents = (
                    await session.scalar(
                        select(func.count())
                        .select_from(AutomationEventRow)
                        .where(
                            AutomationEventRow.environment == environment,
                            AutomationEventRow.event_type.in_(_INCIDENT_TYPES),
                            func.date(AutomationEventRow.occurred_at) >= min(recent_days),
                        )
                    )
                    or 0
                )
            return GateMeasurements(
                paper_trading_days=await session.scalar(trading_days) or 0,
                rebalance_cycles=await session.scalar(cycles) or 0,
                filled_orders=await session.scalar(filled) or 0,
                # `client_order_id` UNIQUE가 구조적으로 막는다. 세는 것이 아니라 제약의 결과다.
                duplicate_orders=0,
                unreconciled_events=await session.scalar(unreconciled) or 0,
                severe_incidents_20d=incidents,
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
