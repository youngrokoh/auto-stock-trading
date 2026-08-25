"""실전 전환 게이트 측정값 읽기. 저장된 사실만 센다.

없는 값은 여기서 만들지 않는다 — 가용성·시나리오·보고서처럼 원천이 없는 조건은 도메인이
'판정 불가'로 표시하며 이 어댑터는 아예 세지 않는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

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

if TYPE_CHECKING:
    from datetime import date

_FILLED_STATES = (OrderState.FILLED.value, OrderState.PARTIALLY_FILLED.value)
_OPEN_STATES = (OrderState.SUBMITTED.value, OrderState.PARTIALLY_FILLED.value)
_SETTLED_STATES = (
    OrderState.FILLED.value,
    OrderState.REJECTED.value,
    OrderState.CANCELED.value,
    OrderState.EXPIRED.value,
)
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

    async def measurements(self, environment: str, as_of: date) -> GateMeasurements:
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
        # 정책은 "미조정 **건**이 0건"이라고 쓴다 — 발생 이력이 아니라 지금 미조정인 건수다. 참조한
        # 주문이 종결됐다면 그 발산은 닫혔다. 이력을 전부 세면 한 번 문제가 생긴 뒤 이 조건은 다시
        # 충족될 수 없고, 정책이 요구하지 않은 영구 차단이 된다.
        settled = (
            select(OrderRow.id)
            .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
            .where(
                OrderPlanRow.environment == environment,
                OrderRow.broker_order_id == AutomationEventRow.detail,
                OrderRow.state.in_(_SETTLED_STATES),
            )
        )
        unreconciled = (
            select(func.count())
            .select_from(AutomationEventRow)
            .where(
                AutomationEventRow.environment == environment,
                AutomationEventRow.event_type == _RECONCILE_PROBLEM,
                # 확인할 주문이 없으면 해소로 보지 않는다. 증권사만 아는 주문은 지금도 미조정이다.
                ~settled.exists(),
            )
        )
        # 거래일 경계를 넘어 남은 미종결 주문. 당일 열린 주문은 정상이므로 세지 않는다.
        stale = (
            select(func.count())
            .select_from(OrderRow)
            .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
            .where(
                OrderPlanRow.environment == environment,
                OrderRow.state.in_(_OPEN_STATES),
                OrderPlanRow.trading_date < as_of,
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
                stale_open_orders=await session.scalar(stale) or 0,
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
