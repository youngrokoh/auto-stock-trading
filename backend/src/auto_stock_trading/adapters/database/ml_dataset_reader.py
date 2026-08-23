"""학습 데이터 조회(ML 신호 계약 §특징·§목표).

확정 일봉만 읽는다. 특징과 목표 계산은 순수 함수가 하고, 이 어댑터는 재료만 모은다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from auto_stock_trading.application.backtests.lineage import symbol_bar_version_hash
from auto_stock_trading.domain.market_data.models import BarFinality
from auto_stock_trading.features.feature_set import FEATURE_SET_PRICE, uses_fundamentals
from auto_stock_trading.features.fundamental_features import (
    FUNDAMENTAL_FEATURE_NAMES,
    fundamental_features,
)
from auto_stock_trading.features.price_features import (
    FeatureBar,
    FeatureRow,
    feature_rows,
)
from auto_stock_trading.features.targets import excess_return

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal
    from typing import Protocol

    from auto_stock_trading.application.backtests.runner import BacktestMarketData
    from auto_stock_trading.domain.market_data.models import VersionedDailyBar
    from auto_stock_trading.domain.strategies.composite_rank import (
        AnnualFact,
        SymbolFundamentals,
    )

    class StrategyFundamentals(Protocol):
        async def read_annual_facts(
            self,
            symbols: tuple[str, ...],
        ) -> tuple[SymbolFundamentals, ...]: ...


@dataclass(frozen=True, slots=True)
class DatasetRequest:
    """데이터셋 범위와 특징 집합. 인자를 늘리는 대신 한 값으로 넘긴다."""

    universe: tuple[str, ...]
    benchmark_symbol: str
    range_start: date
    range_end: date
    feature_version: str = FEATURE_SET_PRICE


@final
class MarketDataTrainingDataset:
    """확정 일봉과 벤치마크로 특징·목표를 만드는 어댑터.

    벤치마크 종가는 비수정 확정 종가를 쓴다(계약의 v3와 같은 한계). 종목 시계열을 벤치마크
    거래일에 맞춰 정렬해, 특징의 시장 지표가 같은 날짜를 보게 한다.
    """

    def __init__(
        self,
        market_data: BacktestMarketData,
        request: DatasetRequest,
        fundamentals: StrategyFundamentals | None = None,
    ) -> None:
        self._market_data = market_data
        self._universe = request.universe
        self._benchmark_symbol = request.benchmark_symbol
        self._range_start = request.range_start
        self._range_end = request.range_end
        self._feature_version = request.feature_version
        self._fundamentals = fundamentals
        self._facts: dict[str, tuple[AnnualFact, ...]] = {}
        self._benchmark: dict[date, Decimal] = {}
        self._dates: tuple[date, ...] = ()
        self._hashed: list[tuple[str, VersionedDailyBar]] = []

    async def _confirmed(self, symbol: str) -> tuple[VersionedDailyBar, ...]:
        bars = await self._market_data.daily_bars(symbol, self._range_start, self._range_end)
        return tuple(
            item
            for item in bars
            if item.finality is BarFinality.CONFIRMED and item.superseded_at is None
        )

    async def _load_benchmark(self) -> None:
        if self._benchmark:
            return
        bars = await self._confirmed(self._benchmark_symbol)
        self._benchmark = {item.bar.trading_date: item.bar.close_price for item in bars}
        self._dates = tuple(sorted(self._benchmark))
        self._hashed.extend((self._benchmark_symbol, item) for item in bars)

    async def trading_dates(self, start: date, end: date) -> tuple[date, ...]:
        """벤치마크 확정 일봉이 있는 날만 거래일로 본다. 시장 특징이 그 날짜를 요구한다."""
        await self._load_benchmark()
        return tuple(day for day in self._dates if start <= day <= end)

    async def universe_symbols(self) -> tuple[str, ...]:
        return self._universe

    async def _annual_facts(self, symbol: str) -> tuple[AnnualFact, ...]:
        if not uses_fundamentals(self._feature_version):
            return ()
        if not self._facts:
            if self._fundamentals is None:
                message = "feature set requires fundamentals but none were provided"
                raise ValueError(message)
            self._facts = {
                item.symbol: item.facts
                for item in await self._fundamentals.read_annual_facts(self._universe)
            }
        return self._facts.get(symbol, ())

    async def feature_rows(self, symbol: str) -> tuple[FeatureRow, ...]:
        await self._load_benchmark()
        bars = await self._confirmed(symbol)
        self._hashed.extend((symbol, item) for item in bars)
        by_date = {item.bar.trading_date: item.bar for item in bars}
        # 벤치마크와 종목이 모두 있는 날짜만 쓴다. 한쪽이 없으면 시장 특징이 어긋난다.
        shared = tuple(day for day in self._dates if day in by_date)
        if not shared:
            return ()
        price_rows = feature_rows(
            tuple(
                FeatureBar(
                    trading_date=day,
                    open_price=by_date[day].open_price,
                    high_price=by_date[day].high_price,
                    low_price=by_date[day].low_price,
                    close_price=by_date[day].close_price,
                    volume=by_date[day].volume,
                    trading_value=by_date[day].trading_value,
                )
                for day in shared
            ),
            tuple(self._benchmark[day] for day in shared),
        )
        if not uses_fundamentals(self._feature_version):
            return price_rows
        facts = await self._annual_facts(symbol)
        combined: list[FeatureRow] = []
        for row in price_rows:
            extra = fundamental_features(
                facts,
                row.trading_date,
                by_date[row.trading_date].close_price,
            )
            if extra is None:
                # 재무를 아직 알 수 없거나 값이 없으면 그 종목-일 표본을 만들지 않는다.
                continue
            combined.append(
                FeatureRow(
                    trading_date=row.trading_date,
                    values={
                        **dict(row.values),
                        **{name: extra[name] for name in FUNDAMENTAL_FEATURE_NAMES},
                    },
                )
            )
        return tuple(combined)

    async def targets(self, symbol: str, horizon_days: int) -> dict[date, Decimal]:
        await self._load_benchmark()
        bars = await self._confirmed(symbol)
        closes = {item.bar.trading_date: item.bar.close_price for item in bars}
        results: dict[date, Decimal] = {}
        for day in self._dates:
            value = excess_return(
                closes,
                self._benchmark,
                self._dates,
                day,
                horizon=horizon_days,
            )
            if value is not None:
                results[day] = value
        return results

    async def bar_version_hash(self) -> str:
        return symbol_bar_version_hash(tuple(self._hashed))

    async def close(self) -> None:
        # 시세 어댑터의 수명은 이 데이터셋을 만든 쪽이 관리한다.
        return None
