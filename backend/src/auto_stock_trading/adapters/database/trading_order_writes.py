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

# 미종결 상태. 종결 상태 4개(체결·거절·취소·기간만료)를 뺀 나머지다.
_UNSETTLED_STATES = (
    OrderState.PLANNED.value,
    OrderState.SUBMITTED.value,
    OrderState.PARTIALLY_FILLED.value,
)


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


def unsettled_orders_query(
    environment: str,
) -> Select[tuple[OrderRow, str, UUID]]:
    """거래일과 무관하게 미종결인 주문(ADR-0017 결정 5). 당일 한정 조회는 한도 계산에만 남긴다."""
    return (
        select(OrderRow, InstrumentRow.symbol, OrderPlanRow.id)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .join(InstrumentRow, OrderRow.instrument_id == InstrumentRow.id)
        .where(
            OrderPlanRow.environment == environment,
            OrderRow.state.in_(_UNSETTLED_STATES),
        )
        .order_by(OrderPlanRow.trading_date, OrderRow.created_at, OrderRow.sequence)
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


async def lock_order(session: AsyncSession, order_id: UUID) -> OrderRow:
    """주문 행을 잠그고 돌려준다. 이벤트 시퀀스를 계산하기 전에 반드시 잠근다.

    상태를 바꾸지 않는 이벤트 기록은 UPDATE가 없어 행이 잠기지 않는다. 그러면 체결통보
    반영과 동시에 같은 `max(sequence)+1`을 잡아 유일 제약을 위반한다(2026-08-21 실측:
    비상정지가 취소를 전달한 뒤 이벤트 기록에서 예외로 끝났다). 비상정지는 사람의 마지막
    통제 수단이므로 부분 실패를 남기면 안 된다.
    """
    current = await session.scalar(
        select(OrderRow).where(OrderRow.id == order_id).with_for_update()
    )
    if current is None:
        message = f"unknown order {order_id}"
        raise LookupError(message)
    return current


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
    current = await lock_order(session, order_id)
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


async def reduce_order_quantity(
    session: AsyncSession,
    order_id: UUID,
    quantity: int,
    reason_code: str,
    occurred_at: datetime,
) -> None:
    """부분 취소로 줄어든 미체결 수량을 반영한다. 상태는 바꾸지 않는다(ADR-0013 결정 6).

    상태 전이가 아니므로 `transition_order`를 쓸 수 없다 — 상태 그래프는 같은 상태로의 전이를
    허용하지 않는다. 이벤트를 붙이기 전에 주문 행을 잠근다: 상태를 바꾸지 않는 기록은 `UPDATE`가
    직렬화해 주지 않으므로 잠금이 없으면 같은 시퀀스를 잡는다(2026-08-21 실측 결함).
    """
    current = await lock_order(session, order_id)
    state = OrderState(current.state)
    # UPDATE 뒤에 읽으면 SQLAlchemy가 갱신된 값을 돌려줘 감사 기록이 `102 -> 102`가 된다.
    # 바뀐 값을 보여야 감사가 성립하므로 변경 전 수량을 먼저 붙잡는다(2026-08-25 장중 실측).
    previous_quantity = current.quantity
    _ = await session.execute(
        update(OrderRow)
        .where(OrderRow.id == order_id)
        .values(quantity=quantity, updated_at=occurred_at)
    )
    session.add(
        OrderEventRow(
            id=uuid4(),
            order_id=order_id,
            sequence=await next_event_sequence(session, order_id),
            previous_state=state.value,
            state=state.value,
            reason_code=reason_code,
            detail=f"quantity {previous_quantity} -> {quantity}",
            occurred_at=occurred_at,
        )
    )
