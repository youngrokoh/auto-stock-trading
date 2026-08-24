"""횡단면 모멘텀 순위(백테스트 계약 v2). 순수 함수이며 저장·조회를 하지 않는다.

모멘텀은 비수정 확정 종가로 계산한다. 수정주가 데이터셋이 유니버스 전체에 없기 때문이며
이 왜곡은 계약의 v2 한계에 기록돼 있다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from auto_stock_trading.domain.strategies.ranking import RankedSymbol, Rebalance, SymbolSeries

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MomentumParameters:
    lookback_days: int
    holdings: int

    def validated(self) -> MomentumParameters:
        if self.lookback_days < 1:
            message = "momentum lookback_days must be at least 1"
            raise ValueError(message)
        if self.holdings < 1:
            message = "momentum holdings must be at least 1"
            raise ValueError(message)
        return self


def momentum_return(series: SymbolSeries, signal_date: date, basis_date: date) -> Decimal | None:
    current = series.closes.get(signal_date)
    basis = series.closes.get(basis_date)
    if current is None or basis is None or basis <= 0:
        return None
    return current / basis - 1


def momentum_rebalances(
    signal_dates: Sequence[date],
    universe: Sequence[SymbolSeries],
    parameters: MomentumParameters,
    trading_dates: Sequence[date],
) -> tuple[Rebalance, ...]:
    """회차별 선정 종목. 동점은 종목코드 오름차순으로 끊어 재현성을 지킨다.

    lookback 구간이 거래일 달력 안에 없으면 그 회차를 만들지 않는다. 기준일을 시그널일로
    되돌리면 전 종목 모멘텀이 0이 되어 코드순 상위 K가 뽑히고, 빈 선정으로 회차를 만들면
    엔진이 보유 전량을 매도한다. 둘 다 전략이 아니다(2026-08-20 실측 결함).
    """
    settings = parameters.validated()
    calendar = tuple(trading_dates)
    index_of = {day: index for index, day in enumerate(calendar)}
    rebalances: list[Rebalance] = []
    for signal_date in signal_dates:
        position = index_of.get(signal_date)
        if position is None:
            continue
        basis_index = position - settings.lookback_days
        if basis_index < 0:
            continue
        ranked = ranked_by_momentum(universe, signal_date, calendar[basis_index])
        if not ranked:
            continue
        rebalances.append(
            Rebalance(
                signal_date=signal_date,
                selected=tuple(ranked[: settings.holdings]),
            )
        )
    return tuple(rebalances)


def ranked_by_momentum(
    universe: Sequence[SymbolSeries],
    signal_date: date,
    basis_date: date,
) -> list[RankedSymbol]:
    candidates = [
        RankedSymbol(symbol=series.symbol, score=value)
        for series in universe
        if (value := momentum_return(series, signal_date, basis_date)) is not None
    ]
    candidates.sort(key=lambda item: (-item.score, item.symbol))
    return candidates
