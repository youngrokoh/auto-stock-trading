"""다종목 전략 신원과 회차 생성기 조립(백테스트 계약 v2·v3).

러너는 전략을 모른다. 여기서 전략 이름·버전·canonical 파라미터와 회차 생성기를 묶어 준다.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final

from auto_stock_trading.application.backtests.lineage import report_version_hash
from auto_stock_trading.application.backtests.portfolio_runner import (
    SignalPlan,
    StrategySpec,
)
from auto_stock_trading.domain.strategies.backtest import BacktestError, BacktestFailure
from auto_stock_trading.domain.strategies.composite_rank import (
    CompositeParameters,
    composite_rebalances,
)
from auto_stock_trading.domain.strategies.momentum import (
    MomentumParameters,
    momentum_rebalances,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from auto_stock_trading.domain.strategies.composite_rank import SymbolFundamentals
    from auto_stock_trading.domain.strategies.ranking import SymbolSeries

MOMENTUM_STRATEGY_NAME: Final = "cross-momentum"
MOMENTUM_STRATEGY_VERSION: Final = "1"
MOMENTUM_SIGNAL_METHOD: Final = "cross_sectional_momentum"

COMPOSITE_STRATEGY_NAME: Final = "composite-rank"
COMPOSITE_STRATEGY_VERSION: Final = "1"
COMPOSITE_SIGNAL_METHOD: Final = "composite_rank"


def canonical_parameters_json(parameters: MomentumParameters | CompositeParameters) -> str:
    return json.dumps(
        {"holdings": parameters.holdings, "lookback_days": parameters.lookback_days},
        separators=(",", ":"),
        sort_keys=True,
    )


@final
@dataclass(frozen=True, slots=True)
class _MomentumSource:
    parameters: MomentumParameters

    def plan(
        self,
        signal_dates: Sequence[date],
        series: Sequence[SymbolSeries],
        trading_dates: Sequence[date],
    ) -> SignalPlan:
        return SignalPlan(
            rebalances=momentum_rebalances(
                signal_dates,
                series,
                self.parameters,
                trading_dates,
            )
        )


@final
@dataclass(frozen=True, slots=True)
class _CompositeSource:
    parameters: CompositeParameters
    fundamentals: tuple[SymbolFundamentals, ...]

    def plan(
        self,
        signal_dates: Sequence[date],
        series: Sequence[SymbolSeries],
        trading_dates: Sequence[date],
    ) -> SignalPlan:
        result = composite_rebalances(
            signal_dates,
            series,
            self.fundamentals,
            self.parameters,
            trading_dates,
        )
        if not result.rebalances:
            raise BacktestError(
                BacktestFailure.NO_SIGNAL_CANDIDATE,
                "no rebalance had a candidate with all three factors",
            )
        return SignalPlan(
            rebalances=result.rebalances,
            report_hash=report_version_hash(result.used_reports),
        )


def momentum_strategy(parameters: MomentumParameters) -> StrategySpec:
    settings = parameters.validated()
    return StrategySpec(
        name=MOMENTUM_STRATEGY_NAME,
        version=MOMENTUM_STRATEGY_VERSION,
        signal_method=MOMENTUM_SIGNAL_METHOD,
        holdings=settings.holdings,
        parameters_json=canonical_parameters_json(settings),
        source=_MomentumSource(settings),
    )


def composite_strategy(
    parameters: CompositeParameters,
    fundamentals: tuple[SymbolFundamentals, ...],
) -> StrategySpec:
    settings = parameters.validated()
    return StrategySpec(
        name=COMPOSITE_STRATEGY_NAME,
        version=COMPOSITE_STRATEGY_VERSION,
        signal_method=COMPOSITE_SIGNAL_METHOD,
        holdings=settings.holdings,
        parameters_json=canonical_parameters_json(settings),
        source=_CompositeSource(settings, fundamentals),
    )
