"""주문 카운터 질의. 쓰기 저장소와 읽기 어댑터가 같은 정의를 공유한다."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import Select, func, select

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.trading_rows import OrderPlanRow, OrderRow
from auto_stock_trading.domain.orders.models import OrderState

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

_OPEN_STATES: Final = (OrderState.SUBMITTED.value, OrderState.PARTIALLY_FILLED.value)
_BUY_COUNTED_STATES: Final = (
    OrderState.PLANNED.value,
    OrderState.SUBMITTED.value,
    OrderState.PARTIALLY_FILLED.value,
    OrderState.FILLED.value,
)
_RECENT_ORDER_LIMIT: Final = 20


def _orders_of(environment: str) -> Select[tuple[int]]:
    return (
        select(func.count())
        .select_from(OrderRow)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .where(OrderPlanRow.environment == environment)
    )


def open_orders_query(environment: str) -> Select[tuple[int]]:
    """정책 §3의 동시 미체결 주문. 제출·부분체결만 미체결로 센다."""
    return _orders_of(environment).where(OrderRow.state.in_(_OPEN_STATES))


def order_attempts_query(environment: str, trading_date: date) -> Select[tuple[int]]:
    return _orders_of(environment).where(OrderPlanRow.trading_date == trading_date)


def _filled_orders_of(environment: str, trading_date: date) -> Select[tuple[int]]:
    """그 거래일의 체결분. 증권사 `output2` 집계도 체결분만 세므로 취소·거절은 자연히 빠진다."""
    return (
        select(func.coalesce(func.sum(OrderRow.filled_quantity), 0))
        .select_from(OrderRow)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .where(
            OrderPlanRow.environment == environment,
            OrderPlanRow.trading_date == trading_date,
            OrderRow.filled_quantity > 0,
        )
    )


def daily_filled_quantity_query(environment: str, trading_date: date) -> Select[tuple[int]]:
    """내부 체결 수량 합계. 증권사 `tot_ccld_qty`와 대조한다(ADR-0017 결정 1)."""
    return _filled_orders_of(environment, trading_date)


def daily_filled_amount_query(environment: str, trading_date: date) -> Select[tuple[int]]:
    """내부 체결 금액 합계(체결 수량 × 평균 체결가). 증권사 `tot_ccld_amt`와 대조한다."""
    return _filled_orders_of(environment, trading_date).with_only_columns(
        func.coalesce(
            func.sum(OrderRow.filled_quantity * OrderRow.average_fill_price),
            Decimal(0),
        )
    )


def buy_amount_query(environment: str, trading_date: date) -> Select[tuple[int]]:
    """합계는 numeric이라 실행 결과는 Decimal이다. 호출자가 Decimal로 변환한다."""
    return (
        select(func.coalesce(func.sum(OrderRow.quantity * OrderRow.limit_price), Decimal(0)))
        .select_from(OrderRow)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .where(
            OrderPlanRow.environment == environment,
            OrderPlanRow.trading_date == trading_date,
            OrderRow.side == "buy",
            OrderRow.state.in_(_BUY_COUNTED_STATES),
        )
    )


def max_order_amount_query(environment: str, trading_date: date) -> Select[tuple[int]]:
    """정책 §3의 주문 1건 금액 소진율에 쓰는 그 거래일 최대 주문 금액(실행 결과는 Decimal)."""
    return (
        select(func.coalesce(func.max(OrderRow.quantity * OrderRow.limit_price), Decimal(0)))
        .select_from(OrderRow)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .where(
            OrderPlanRow.environment == environment,
            OrderPlanRow.trading_date == trading_date,
        )
    )


_PENDING_STATES: Final = (
    OrderState.PLANNED.value,
    OrderState.SUBMITTED.value,
    OrderState.PARTIALLY_FILLED.value,
)


def pending_exposure_query(environment: str, trading_date: date) -> Select[tuple[str, int]]:
    """정책 §2의 예상 노출: 아직 체결되지 않은 수량 × 지정가를 종목별로 합산한다."""
    return (
        select(
            InstrumentRow.symbol,
            func.coalesce(
                func.sum((OrderRow.quantity - OrderRow.filled_quantity) * OrderRow.limit_price),
                Decimal(0),
            ),
        )
        .select_from(OrderRow)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .join(InstrumentRow, OrderRow.instrument_id == InstrumentRow.id)
        .where(
            OrderPlanRow.environment == environment,
            OrderPlanRow.trading_date == trading_date,
            OrderRow.state.in_(_PENDING_STATES),
            OrderRow.limit_price.is_not(None),
        )
        .group_by(InstrumentRow.symbol)
    )


def recent_states_query(environment: str) -> Select[tuple[str]]:
    return (
        select(OrderRow.state)
        .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
        .where(OrderPlanRow.environment == environment)
        .order_by(OrderRow.created_at.desc(), OrderRow.sequence.desc())
        .limit(_RECENT_ORDER_LIMIT)
    )


def consecutive_rejects(states: Sequence[str]) -> int:
    """최신 주문부터 연속으로 거절된 건수."""
    consecutive = 0
    for state in states:
        if state != OrderState.REJECTED.value:
            break
        consecutive += 1
    return consecutive
