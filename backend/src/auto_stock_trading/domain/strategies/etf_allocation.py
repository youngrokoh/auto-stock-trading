"""ETF 모멘텀 자산배분 유니버스. 사용자가 2026-08-24에 승인한 6종이다.

**이름으로 고르지 않았다.** `market.etf_nav`의 원천 필드로 걸렀다: 추적배수 1.00(정책 §1이
레버리지·인버스 신규 매수를 금지한다), 순자산총액 상위, 그리고 추종지수가 서로 다른 자산군.

구간은 가장 늦게 상장된 자산(미국채 20년+, 2023-03-14)이 정한다. 그 앞 구간에는 자산배분이 성립하지
않으므로 백테스트 시작점으로 쓴다. 자산군을 줄여 구간을 늘리는 대안은 검토했고, 자산배분 전략은
자산군이 서로 다를 때 의미가 생기므로 다양성을 택했다(사용자 승인).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.strategies.momentum import (
    momentum_return,
    ranked_by_momentum,
)
from auto_stock_trading.domain.strategies.ranking import RankedSymbol, Rebalance

if TYPE_CHECKING:
    from collections.abc import Sequence
    from decimal import Decimal

    from auto_stock_trading.domain.strategies.ranking import SymbolSeries


class AssetClass(StrEnum):
    """자산군. 하나에 하나의 ETF만 들어간다."""

    DOMESTIC_EQUITY = "domestic_equity"
    US_EQUITY = "us_equity"
    US_GROWTH = "us_growth"
    GOLD = "gold"
    US_TREASURY = "us_treasury"
    CASH_PROXY = "cash_proxy"


@dataclass(frozen=True, slots=True)
class AllocationEntry:
    """유니버스 한 종목. 수치는 2026-08-24 수집 스냅샷에서 읽은 사실이다."""

    symbol: str
    asset_class: AssetClass
    index_name: str
    listed_on: date
    tracking_multiple: int
    net_asset_total: int


ALLOCATION_UNIVERSE: Final = (
    AllocationEntry(
        symbol="069500",
        asset_class=AssetClass.DOMESTIC_EQUITY,
        index_name="KOSPI200",
        listed_on=date(2002, 10, 14),
        tracking_multiple=1,
        net_asset_total=260_643,
    ),
    AllocationEntry(
        symbol="360750",
        asset_class=AssetClass.US_EQUITY,
        index_name="S&P 500",
        listed_on=date(2020, 8, 7),
        tracking_multiple=1,
        net_asset_total=209_545,
    ),
    AllocationEntry(
        symbol="133690",
        asset_class=AssetClass.US_GROWTH,
        index_name="NASDAQ 100",
        listed_on=date(2010, 10, 18),
        tracking_multiple=1,
        net_asset_total=117_922,
    ),
    AllocationEntry(
        symbol="411060",
        asset_class=AssetClass.GOLD,
        index_name="KRX 금현물지수",
        listed_on=date(2021, 12, 15),
        tracking_multiple=1,
        net_asset_total=40_751,
    ),
    AllocationEntry(
        symbol="453850",
        asset_class=AssetClass.US_TREASURY,
        index_name="Bloomberg U.S Treasury 20+ Year Total Return Index",
        listed_on=date(2023, 3, 14),
        tracking_multiple=1,
        net_asset_total=15_031,
    ),
    AllocationEntry(
        symbol="357870",
        asset_class=AssetClass.CASH_PROXY,
        index_name="KIS CD금리투자 총수익지수",
        listed_on=date(2020, 7, 7),
        tracking_multiple=1,
        net_asset_total=35_489,
    ),
)

# 공통 구간의 시작. 가장 늦은 상장일이며, 그 앞에는 6자산 배분이 성립하지 않는다.
ALLOCATION_WINDOW_START: Final = max(entry.listed_on for entry in ALLOCATION_UNIVERSE)


def allocation_symbols() -> tuple[str, ...]:
    """수집·백테스트가 쓰는 종목코드. 정렬해 돌려주므로 실행 순서가 재현된다."""
    return tuple(sorted(entry.symbol for entry in ALLOCATION_UNIVERSE))


# 대피처. 승인된 유니버스의 현금성 자산이며, 절대 모멘텀 조건에 걸린 자리를 이것으로 채운다.
CASH_PROXY_SYMBOL: Final = "357870"


@dataclass(frozen=True, slots=True)
class EtfAllocationParameters:
    """전략 파라미터. `lookback_days`는 거래일 수이며 12개월은 약 250거래일이다."""

    lookback_days: int
    holdings: int

    def validated(self) -> EtfAllocationParameters:
        if self.lookback_days < 1:
            message = "etf allocation lookback_days must be at least 1"
            raise ValueError(message)
        if self.holdings < 1:
            message = "etf allocation holdings must be at least 1"
            raise ValueError(message)
        return self


def _shelter(
    ranked: Sequence[RankedSymbol],
    holdings: int,
    cash_score: Decimal,
) -> tuple[RankedSymbol, ...]:
    """상위 N 중 수익률이 음수인 자리를 현금성으로 바꾼다.

    같은 종목을 두 자리에 넣을 수 없으므로 중복은 하나로 접는다. 그 경우 엔진이 NAV를 고정 보유
    개수로 나누기 때문에 남는 자리는 미투자 현금이 된다 — 수익 0이라 CD ETF보다 보수적이다.

    기록하는 점수는 **실제로 보유하는 자산**의 모멘텀이다. 배제된 자산의 점수를 남기면 감사에서
    보유 근거가 틀린다.
    """
    chosen: list[RankedSymbol] = []
    seen: set[str] = set()
    for item in ranked[:holdings]:
        entry = item if item.score > 0 else RankedSymbol(symbol=CASH_PROXY_SYMBOL, score=cash_score)
        if entry.symbol in seen:
            continue
        seen.add(entry.symbol)
        chosen.append(entry)
    return tuple(chosen)


def etf_allocation_rebalances(
    signal_dates: Sequence[date],
    universe: Sequence[SymbolSeries],
    parameters: EtfAllocationParameters,
    trading_dates: Sequence[date],
) -> tuple[Rebalance, ...]:
    """회차별 목표 보유. 상대 서열로 뽑고 절대 모멘텀으로 대피시킨다(2026-08-24 승인).

    lookback 구간이 달력 안에 없는 회차는 만들지 않는다. 대피처(현금성 ETF)의 모멘텀을 계산할 수
    없는 회차도 만들지 않는다 — 대피할 수 없는 상태를 통과시키면 음수 자산을 그대로 보유한다.
    """
    settings = parameters.validated()
    calendar = tuple(trading_dates)
    index_of = {day: index for index, day in enumerate(calendar)}
    cash_series = next(
        (series for series in universe if series.symbol == CASH_PROXY_SYMBOL),
        None,
    )
    rebalances: list[Rebalance] = []
    for signal_date in signal_dates:
        position = index_of.get(signal_date)
        if position is None:
            continue
        basis_index = position - settings.lookback_days
        if basis_index < 0:
            continue
        basis_date = calendar[basis_index]
        cash_score = (
            None if cash_series is None else momentum_return(cash_series, signal_date, basis_date)
        )
        if cash_score is None:
            continue
        ranked = ranked_by_momentum(universe, signal_date, basis_date)
        if not ranked:
            continue
        rebalances.append(
            Rebalance(
                signal_date=signal_date,
                selected=_shelter(ranked, settings.holdings, cash_score),
            )
        )
    return tuple(rebalances)
