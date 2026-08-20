"""횡단면 모멘텀 순위(백테스트 계약 v2). 순수 함수이며 저장·조회를 하지 않는다.

모멘텀은 비수정 확정 종가로 계산한다. 수정주가 데이터셋이 유니버스 전체에 없기 때문이며
이 왜곡은 계약의 v2 한계에 기록돼 있다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
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


@dataclass(frozen=True, slots=True)
class SymbolSeries:
    """종목 하나의 확정 종가. 없는 날짜는 확정 일봉이 없다는 뜻이다."""

    symbol: str
    closes: Mapping[date, Decimal]


@dataclass(frozen=True, slots=True)
class RankedSymbol:
    symbol: str
    momentum: Decimal


@dataclass(frozen=True, slots=True)
class Rebalance:
    signal_date: date
    selected: tuple[RankedSymbol, ...]


def rebalance_dates(trading_dates: Sequence[date]) -> tuple[date, ...]:
    """각 달의 마지막 거래일. 창의 마지막 거래일도 회차로 본다."""
    dates = tuple(trading_dates)
    return tuple(
        current
        for index, current in enumerate(dates)
        if index + 1 == len(dates) or dates[index + 1].month != current.month
    )


def _momentum(series: SymbolSeries, signal_date: date, basis_date: date) -> Decimal | None:
    current = series.closes.get(signal_date)
    basis = series.closes.get(basis_date)
    if current is None or basis is None or basis <= 0:
        return None
    return current / basis - 1


def momentum_rebalances(
    signal_dates: Sequence[date],
    universe: Sequence[SymbolSeries],
    parameters: MomentumParameters,
    trading_dates: Sequence[date] | None = None,
) -> tuple[Rebalance, ...]:
    """회차별 선정 종목. 동점은 종목코드 오름차순으로 끊어 재현성을 지킨다."""
    settings = parameters.validated()
    calendar = tuple(trading_dates) if trading_dates is not None else tuple(signal_dates)
    index_of = {day: index for index, day in enumerate(calendar)}
    rebalances: list[Rebalance] = []
    for signal_date in signal_dates:
        position = index_of.get(signal_date)
        basis_index = -1 if position is None else position - settings.lookback_days
        basis_date = (
            _basis_from_series(universe, signal_date, settings.lookback_days)
            if basis_index < 0
            else calendar[basis_index]
        )
        ranked = _ranked(universe, signal_date, basis_date)
        rebalances.append(
            Rebalance(
                signal_date=signal_date,
                selected=tuple(ranked[: settings.holdings]),
            )
        )
    return tuple(rebalances)


def _basis_from_series(
    universe: Sequence[SymbolSeries],
    signal_date: date,
    lookback_days: int,
) -> date:
    """거래일 목록을 따로 주지 않으면 종목들이 가진 날짜 합집합을 달력으로 쓴다."""
    days = sorted({day for series in universe for day in series.closes if day <= signal_date})
    position = len(days) - 1 - lookback_days
    return days[position] if position >= 0 else signal_date


def _ranked(
    universe: Sequence[SymbolSeries],
    signal_date: date,
    basis_date: date,
) -> list[RankedSymbol]:
    candidates = [
        RankedSymbol(symbol=series.symbol, momentum=value)
        for series in universe
        if (value := _momentum(series, signal_date, basis_date)) is not None
    ]
    candidates.sort(key=lambda item: (-item.momentum, item.symbol))
    return candidates
