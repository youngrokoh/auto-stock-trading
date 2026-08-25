"""세션 종료 시 열린 주문 처리와 계좌 단위 재대조 판정. 순수 함수다(ADR-0017).

모의환경의 일별주문체결조회는 주문별 행(`output1`)을 주지 않는다(독립 측정 3회). 대신 같은 응답의
`output2`가 계좌 단위 당일 집계를 준다. 그래서 재대조는 **합계 수준**이고, 주문별 귀속은 만들지
않는다 — 합계가 맞는데 어느 주문의 것인지 배분하면 사실이 아니라 우리가 만든 값이 된다.

**집계 일치만이 종결 근거다.** 정규장이 끝나면 미체결 주문은 체결될 수 없지만 그것은 우리가 관측한
사실이 아니다. 집계가 우리 내부 체결 합계와 맞으면 "우리가 미체결로 아는 주문이 실제로도 체결되지
않았다"가 관측으로 확인된다. 이 방향의 추론만 유효하다 — 집계는 체결분만 세므로 미체결 주문이 몇 건
살아 있는지는 알려주지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.orders.fills import ReconcileProblem
from auto_stock_trading.domain.orders.models import OrderState

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from decimal import Decimal

    from auto_stock_trading.domain.orders.fills import OrderSnapshot

# 종결하지 않는 상태. 나머지는 이미 종결이므로 다시 종결하지 않는다.
_OPEN_STATES = frozenset({OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED})

_SEOUL: Final = ZoneInfo("Asia/Seoul")
# 정규장 종료. 종가 단일가(15:20~15:30)까지 체결될 수 있으므로 주문 허용시간 종료(15:15)가 아니라
# 장 종료를 기준으로 한다.
SESSION_END: Final = time(15, 30)


def session_ended(now: datetime) -> bool:
    """서울 기준으로 정규장이 끝났는지. 장중에는 종결 판단을 하지 않는다."""
    return now.astimezone(_SEOUL).time() >= SESSION_END


class AggregateVerdict(StrEnum):
    """계좌 단위 재대조 결과. 대조 불가는 일치가 아니다."""

    MATCHED = "matched"
    MISMATCHED = "mismatched"
    # 증권사가 집계를 주지 않았다. 빈 응답을 성공으로 읽지 않기 위해 별도 상태로 둔다.
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class BrokerDailyTotals:
    """`output2`의 당일 집계. 체결분만 센다(`tot_ord_qty == tot_ccld_qty` 실측)."""

    filled_quantity: int
    filled_amount: Decimal


@dataclass(frozen=True, slots=True)
class InternalDailyTotals:
    """우리가 기록한 당일 체결 합계."""

    filled_quantity: int
    filled_amount: Decimal


@dataclass(frozen=True, slots=True)
class SessionCloseOutcome:
    client_order_id: str
    state: OrderState
    filled_quantity: int
    closed: bool
    problem: ReconcileProblem | None


def compare_daily_totals(
    internal: InternalDailyTotals,
    broker: BrokerDailyTotals | None,
) -> AggregateVerdict:
    """수량과 금액이 모두 같을 때만 일치다. 어느 쪽이 틀렸는지 모르므로 맞추지 않는다."""
    if broker is None:
        return AggregateVerdict.UNAVAILABLE
    if internal.filled_quantity != broker.filled_quantity:
        return AggregateVerdict.MISMATCHED
    if internal.filled_amount != broker.filled_amount:
        return AggregateVerdict.MISMATCHED
    return AggregateVerdict.MATCHED


_PROBLEMS = {
    AggregateVerdict.MISMATCHED: ReconcileProblem.DAILY_TOTALS_MISMATCH,
    AggregateVerdict.UNAVAILABLE: ReconcileProblem.DAILY_TOTALS_UNAVAILABLE,
}


def close_session_orders(
    open_orders: Iterable[OrderSnapshot],
    verdict: AggregateVerdict,
) -> tuple[SessionCloseOutcome, ...]:
    """집계가 일치할 때만 `expired`로 옮긴다. 아니면 열린 채로 두고 문제를 남긴다.

    체결분은 사실이므로 그대로 보존한다. 새로 생기는 사실은 "남은 수량은 체결되지 않는다"뿐이다.
    """
    matched = verdict is AggregateVerdict.MATCHED
    problem = _PROBLEMS.get(verdict)
    return tuple(
        SessionCloseOutcome(
            client_order_id=order.client_order_id,
            state=OrderState.EXPIRED if matched else order.state,
            filled_quantity=order.filled_quantity,
            closed=matched,
            problem=problem,
        )
        for order in open_orders
        if order.state in _OPEN_STATES
    )
