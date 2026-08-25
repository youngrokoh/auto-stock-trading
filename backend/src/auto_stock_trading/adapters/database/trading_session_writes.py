"""세션 종료 종결과 내부 체결 합계(ADR-0017). `trading_store.py`가 이미 검토 한계를 넘어 분리한다.

종결은 체결 동기화와 다른 사건이므로 사유 코드도 다르다. `apply_fill`의 사유를 재사용하면 감사
기록에서 "증권사가 체결을 알려줬다"와 "장이 끝나 더 체결될 수 없다"가 구분되지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final

from auto_stock_trading.adapters.database.trading_order_writes import (
    OrderTransition,
    transition_order,
)
from auto_stock_trading.adapters.database.trading_queries import (
    daily_filled_amount_query,
    daily_filled_quantity_query,
)
from auto_stock_trading.domain.orders.models import OrderState
from auto_stock_trading.domain.orders.session_close import InternalDailyTotals

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

SESSION_ENDED: Final = "SESSION_ENDED"


async def expire_order(
    session: AsyncSession,
    order_id: UUID,
    evidence: str,
    occurred_at: datetime,
) -> None:
    """더 체결될 수 없음이 집계로 확인된 주문을 종결한다. 체결분은 건드리지 않는다."""
    await transition_order(
        session,
        OrderTransition(
            order_id=order_id,
            state=OrderState.EXPIRED,
            reason_code=SESSION_ENDED,
            occurred_at=occurred_at,
            values={},
            detail=evidence,
        ),
    )


async def read_daily_fill_totals(
    session: AsyncSession,
    environment: str,
    trading_date: date,
) -> InternalDailyTotals:
    quantity = await session.scalar(daily_filled_quantity_query(environment, trading_date))
    amount = await session.scalar(daily_filled_amount_query(environment, trading_date))
    return InternalDailyTotals(
        filled_quantity=quantity or 0,
        filled_amount=Decimal(amount or 0),
    )
