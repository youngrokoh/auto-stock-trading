"""실주문 신호 생성(ADR-0016). 백테스트와 **같은 코드**로 목표를 만든다.

전략 규칙은 `domain/strategies/etf_allocation.py`를 그대로 호출한다. 실주문용으로 다시 구현하면
백테스트로 검증한 전략과 실제로 주문하는 전략이 갈라진다.

입력은 **확정 봉만**이다. 일봉 확정은 15:40 KST 이후 두 번 일치 관측을 요구하므로 장중에 쓸 수 있는
가장 최근 기준일은 T-1이며, 이는 백테스트의 "T 종가 신호 → 다음 거래일 체결" 구조와 같다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from auto_stock_trading.application.backtests.lineage import bar_version_hash
from auto_stock_trading.domain.market_data.models import BarFinality
from auto_stock_trading.domain.strategies.etf_allocation import (
    ALLOCATION_WINDOW_START,
    EtfAllocationParameters,
    allocation_symbols,
    etf_allocation_rebalances,
)
from auto_stock_trading.domain.strategies.live_signal import completed_rebalance_dates
from auto_stock_trading.domain.strategies.ranking import SymbolSeries

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from auto_stock_trading.domain.market_data.models import VersionedDailyBar
    from auto_stock_trading.domain.strategies.ranking import RankedSymbol

STRATEGY_NAME: Final = "etf-allocation-momentum"
STRATEGY_VERSION: Final = "1"

NO_CONFIRMED_BARS: Final = "NO_CONFIRMED_BARS"
NO_COMPLETED_REBALANCE: Final = "NO_COMPLETED_REBALANCE"


@dataclass(frozen=True, slots=True)
class LiveSignal:
    """저장될 신호 한 건. 계보가 함께 있어야 감사가 성립한다."""

    strategy_name: str
    strategy_version: str
    parameters_json: str
    basis_date: date
    rebalance_date: date
    bar_version_hash: str
    basis_close: tuple[tuple[str, Decimal], ...]
    targets: tuple[RankedSymbol, ...]


@dataclass(frozen=True, slots=True)
class SignalOutcome:
    signal: LiveSignal | None
    reason: str | None


class BarSource(Protocol):
    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[VersionedDailyBar, ...]: ...


def _confirmed(bars: tuple[VersionedDailyBar, ...]) -> tuple[VersionedDailyBar, ...]:
    return tuple(
        item
        for item in bars
        if item.finality is BarFinality.CONFIRMED and item.superseded_at is None
    )


@dataclass(frozen=True, slots=True)
class LiveSignalGenerator:
    """확정 봉으로 현재 목표를 만든다. 값을 만들지 않는다 — 못 만들면 사유를 돌려준다."""

    bars: BarSource
    parameters: EtfAllocationParameters

    async def generate(self, now: datetime) -> SignalOutcome:
        del now  # 기준일은 시각이 아니라 확정 봉이 정한다.
        series: list[SymbolSeries] = []
        collected: list[VersionedDailyBar] = []
        closes: dict[str, tuple[date, Decimal]] = {}
        for symbol in allocation_symbols():
            confirmed = _confirmed(
                await self.bars.daily_bars(symbol, ALLOCATION_WINDOW_START, None)
            )
            if not confirmed:
                return SignalOutcome(signal=None, reason=NO_CONFIRMED_BARS)
            collected.extend(confirmed)
            series.append(
                SymbolSeries(
                    symbol=symbol,
                    closes={item.bar.trading_date: item.bar.close_price for item in confirmed},
                )
            )
            last = confirmed[-1]
            closes[symbol] = (last.bar.trading_date, last.bar.close_price)
        return self._build(series, tuple(collected), closes)

    def _build(
        self,
        series: list[SymbolSeries],
        collected: tuple[VersionedDailyBar, ...],
        closes: dict[str, tuple[date, Decimal]],
    ) -> SignalOutcome:
        # 모든 종목이 가진 가장 최근 확정 거래일이 기준일이다. 한 종목이라도
        # 뒤처지면 그 날까지만 본다.
        basis_date = min(trading_date for trading_date, _ in closes.values())
        calendar = sorted({day for item in series for day in item.closes if day <= basis_date})
        rebalance_days = completed_rebalance_dates(calendar)
        if not rebalance_days:
            return SignalOutcome(signal=None, reason=NO_COMPLETED_REBALANCE)
        rebalances = etf_allocation_rebalances(
            rebalance_days,
            series,
            self.parameters,
            calendar,
        )
        if not rebalances:
            return SignalOutcome(signal=None, reason=NO_COMPLETED_REBALANCE)
        latest = rebalances[-1]
        return SignalOutcome(
            signal=LiveSignal(
                strategy_name=STRATEGY_NAME,
                strategy_version=STRATEGY_VERSION,
                parameters_json=json.dumps(
                    {
                        "holdings": self.parameters.holdings,
                        "lookback_days": self.parameters.lookback_days,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                basis_date=basis_date,
                rebalance_date=latest.signal_date,
                bar_version_hash=bar_version_hash(collected),
                basis_close=tuple((symbol, price) for symbol, (_, price) in sorted(closes.items())),
                targets=latest.selected,
            ),
            reason=None,
        )
