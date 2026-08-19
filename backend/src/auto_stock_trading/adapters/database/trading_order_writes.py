"""주문 상태 전이의 공용 쓰기 헬퍼. 여러 저장소가 같은 트랜잭션 규칙을 공유한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Select, func, select, update

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.trading_rows import (
    OrderEventRow,
    OrderPlanRow,
    OrderRow,
)
from auto_stock_trading.application.trading.submission import TrackedOrder
from auto_stock_trading.domain.orders.models import (
    OrderSide,
    OrderState,
    next_order_state,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def tracked_orders_query(
    environment: str,
    trading_date: date,
) -> Select[tuple[OrderRow, str, UUID]]:
    return (
        select(OrderRow, InstrumentRow.symbol, OrderPlanRow.id)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .join(InstrumentRow, OrderRow.instrument_id == InstrumentRow.id)
        .where(
            OrderPlanRow.environment == environment,
            OrderPlanRow.trading_date == trading_date,
        )
        .order_by(OrderRow.created_at, OrderRow.sequence)
    )


def broker_order_query(
    environment: str,
    broker_order_id: str,
) -> Select[tuple[OrderRow, str, UUID]]:
    """증권사 주문번호로 내부 주문을 찾는다. 통보 대조의 유일한 연결 키다."""
    return (
        select(OrderRow, InstrumentRow.symbol, OrderPlanRow.id)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .join(InstrumentRow, OrderRow.instrument_id == InstrumentRow.id)
        .where(
            OrderPlanRow.environment == environment,
            OrderRow.broker_order_id == broker_order_id,
        )
        .limit(1)
    )


def tracked_order(row: OrderRow, symbol: str, plan_id: UUID) -> TrackedOrder:
    return TrackedOrder(
        order_id=row.id,
        plan_id=plan_id,
        client_order_id=row.client_order_id,
        symbol=symbol,
        side=OrderSide(row.side),
        quantity=row.quantity,
        filled_quantity=row.filled_quantity,
        average_fill_price=row.average_fill_price,
        limit_price=row.limit_price,
        state=OrderState(row.state),
        broker_order_id=row.broker_order_id,
        broker_org_no=row.broker_org_no,
    )


async def next_event_sequence(session: AsyncSession, order_id: UUID) -> int:
    highest = await session.scalar(
        select(func.max(OrderEventRow.sequence)).where(OrderEventRow.order_id == order_id)
    )
    return (highest or 0) + 1


@dataclass(frozen=True, slots=True)
class OrderTransition:
    order_id: UUID
    state: OrderState
    reason_code: str | None
    occurred_at: datetime
    values: dict[str, object]
    detail: str | None = None


async def transition_order(session: AsyncSession, transition: OrderTransition) -> None:
    """상태 그래프를 검증한 뒤 현재 상태 1행과 이벤트 로그를 함께 갱신한다."""
    order_id = transition.order_id
    current = await session.scalar(select(OrderRow).where(OrderRow.id == order_id))
    if current is None:
        message = f"unknown order {order_id}"
        raise LookupError(message)
    previous = OrderState(current.state)
    requested = next_order_state(previous, transition.state)
    _ = await session.execute(
        update(OrderRow)
        .where(OrderRow.id == order_id)
        .values(
            state=requested.value,
            updated_at=transition.occurred_at,
            **transition.values,
        )
    )
    session.add(
        OrderEventRow(
            id=uuid4(),
            order_id=order_id,
            sequence=await next_event_sequence(session, order_id),
            previous_state=previous.value,
            state=requested.value,
            reason_code=transition.reason_code,
            detail=transition.detail,
            occurred_at=transition.occurred_at,
        )
    )
