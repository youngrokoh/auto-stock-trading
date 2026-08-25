"""실주문 신호의 순수 규칙(ADR-0016). 백테스트 규칙을 다시 구현하지 않는다.

여기 있는 것은 백테스트에 없던 두 가지뿐이다.

1. **완결된 회차**: 백테스트의 `rebalance_dates`는 창의 마지막 거래일도 회차로 본다 — 장부를 닫아야
   하기 때문이다. 실주문에서 T-1까지의 창에 그 규칙을 쓰면 **매일이 회차**가 되어 월말 전략이 일간
   전략으로 바뀐다. 그래서 "다음 거래일이 다른 달"인 날만 회차로 센다.
2. **후보 변환**: 목표와 보유의 차집합이다. 교집합은 건드리지 않는다(비중 조정은 별도 결정).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from auto_stock_trading.domain.orders.models import OrderSide
from auto_stock_trading.domain.risk.engine import SignalCandidate

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from auto_stock_trading.domain.strategies.ranking import RankedSymbol


def completed_rebalance_dates(trading_dates: Sequence[date]) -> tuple[date, ...]:
    """완결된 월말 회차만. 창의 마지막 거래일은 회차로 보지 않는다."""
    dates = tuple(trading_dates)
    return tuple(
        current
        for index, current in enumerate(dates)
        if index + 1 < len(dates) and dates[index + 1].month != current.month
    )


def signal_candidates(
    targets: Sequence[RankedSymbol],
    holdings: Sequence[str],
) -> tuple[SignalCandidate, ...]:
    """목표와 보유의 차집합. 순서를 고정해 계획 재실행이 흔들리지 않게 한다.

    목표에 있고 보유에 없으면 매수, 보유에 있고 목표에 없으면 매도. 둘 다 있으면 아무것도 하지
    않는다 — 비중을 맞추려면 부분 매도 판단이 필요하고 그것은 이 결정의 범위 밖이다.
    """
    target_symbols = {item.symbol for item in targets}
    held = set(holdings)
    buys = tuple(SignalCandidate(symbol, OrderSide.BUY) for symbol in sorted(target_symbols - held))
    sells = tuple(
        SignalCandidate(symbol, OrderSide.SELL) for symbol in sorted(held - target_symbols)
    )
    return buys + sells
