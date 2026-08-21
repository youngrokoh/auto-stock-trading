"""학습 목표 생성(ML 신호 계약 §목표). 순수 함수다.

목표는 절대 수익률이 아니라 같은 날 종목들 사이의 상대 순위다. 상승·하락 국면 어느 쪽에서도
비교가 성립하고, 상위 K 동일가중 전략에 그대로 대응한다.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

TARGET_HORIZON_DAYS: Final = 20
_MIN_CROSS_SECTION: Final = 2
_TWO: Final = Decimal(2)


def excess_return(
    closes: Mapping[date, Decimal],
    benchmark_closes: Mapping[date, Decimal],
    trading_dates: Sequence[date],
    signal_date: date,
    horizon: int = TARGET_HORIZON_DAYS,
) -> Decimal | None:
    """시그널일부터 `horizon` 거래일 뒤까지의 벤치마크 대비 초과수익.

    창을 벗어나거나 어느 한쪽 종가가 없으면 목표를 만들지 않는다. 추정하지 않는다.
    """
    dates = tuple(trading_dates)
    try:
        position = dates.index(signal_date)
    except ValueError:
        return None
    future = position + horizon
    if future >= len(dates):
        return None
    future_date = dates[future]
    start = closes.get(signal_date)
    end = closes.get(future_date)
    base = benchmark_closes.get(signal_date)
    target = benchmark_closes.get(future_date)
    if start is None or end is None or base is None or target is None:
        return None
    if start <= 0 or base <= 0:
        return None
    return (end / start - 1) - (target / base - 1)


def cross_sectional_ranks(excess_by_symbol: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """초과수익을 0~1 백분위로 바꾼다. 1이 가장 우수하고 동점은 백분위를 나눠 갖는다.

    후보가 둘 미만이면 상대 순위가 의미를 갖지 못하므로 빈 결과를 돌려준다.
    """
    if len(excess_by_symbol) < _MIN_CROSS_SECTION:
        return {}
    ordered = sorted(excess_by_symbol.items(), key=lambda item: (item[1], item[0]))
    last = Decimal(len(ordered) - 1)
    percentiles: dict[str, Decimal] = {}
    index = 0
    while index < len(ordered):
        stop = index
        while stop + 1 < len(ordered) and ordered[stop + 1][1] == ordered[index][1]:
            stop += 1
        shared = (Decimal(index) + Decimal(stop)) / _TWO / last
        for symbol, _ in ordered[index : stop + 1]:
            percentiles[symbol] = shared
        index = stop + 1
    return percentiles
