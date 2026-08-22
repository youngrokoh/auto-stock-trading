"""횡단면 전략의 공용 타입과 순위 계산(백테스트 계약 v2·v3).

모멘텀 단일 요인과 종합 순위가 같은 회차 정의·같은 선정 타입을 쓰게 한다. 요인별 순위는
동점에 평균 순위를 준다. 종목코드로 끊으면 코드가 앞선 종목에 체계적 이득이 생긴다.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

_TWO: Final = Decimal(2)
SCORE_QUANTUM: Final = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class SymbolSeries:
    """종목 하나의 확정 종가. 없는 날짜는 확정 일봉이 없다는 뜻이다."""

    symbol: str
    closes: Mapping[date, Decimal]


@dataclass(frozen=True, slots=True)
class RankedSymbol:
    """선정된 종목과 그 전략의 점수. 점수 정의는 전략마다 다르다."""

    symbol: str
    score: Decimal


@dataclass(frozen=True, slots=True)
class Rebalance:
    signal_date: date
    selected: tuple[RankedSymbol, ...]
    # 보유 중이면 팔지 않고 유지할 종목(교체 임계). 비어 있으면 기존 동작과 같다 —
    # 선정에서 빠진 보유는 전량 매도된다.
    retained: tuple[str, ...] = ()


def rebalance_dates(trading_dates: Sequence[date]) -> tuple[date, ...]:
    """각 달의 마지막 거래일. 창의 마지막 거래일도 회차로 본다."""
    dates = tuple(trading_dates)
    return tuple(
        current
        for index, current in enumerate(dates)
        if index + 1 == len(dates) or dates[index + 1].month != current.month
    )


def descending_ranks(values: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """값이 큰 쪽이 1위. 동점은 차지한 순위들의 평균을 나눠 갖는다."""
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    ranks: dict[str, Decimal] = {}
    index = 0
    while index < len(ordered):
        stop = index
        while stop + 1 < len(ordered) and ordered[stop + 1][1] == ordered[index][1]:
            stop += 1
        # 1-기반 순위 index+1 .. stop+1 의 평균
        shared = (Decimal(index + 1) + Decimal(stop + 1)) / _TWO
        for symbol, _ in ordered[index : stop + 1]:
            ranks[symbol] = shared
        index = stop + 1
    return ranks


def quantized_score(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)
