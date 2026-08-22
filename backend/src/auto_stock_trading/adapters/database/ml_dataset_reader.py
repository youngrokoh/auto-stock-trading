"""학습 데이터 조회(ML 신호 계약 §특징·§목표).

확정 일봉만 읽는다. 특징과 목표 계산은 순수 함수가 하고, 이 어댑터는 재료만 모은다.
"""

from typing import TYPE_CHECKING, final

from auto_stock_trading.application.backtests.lineage import symbol_bar_version_hash
from auto_stock_trading.domain.market_data.models import BarFinality
from auto_stock_trading.features.price_features import FeatureBar, feature_rows
from auto_stock_trading.features.targets import excess_return

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from auto_stock_trading.application.backtests.runner import BacktestMarketData
    from auto_stock_trading.domain.market_data.models import VersionedDailyBar
    from auto_stock_trading.features.price_features import FeatureRow


@final
class MarketDataTrainingDataset:
    """확정 일봉과 벤치마크로 특징·목표를 만드는 어댑터.

    벤치마크 종가는 비수정 확정 종가를 쓴다(계약의 v3와 같은 한계). 종목 시계열을 벤치마크
    거래일에 맞춰 정렬해, 특징의 시장 지표가 같은 날짜를 보게 한다.
    """

    def __init__(
        self,
        market_data: BacktestMarketData,
        universe: tuple[str, ...],
        benchmark_symbol: str,
        range_start: date,
        range_end: date,
    ) -> None:
        self._market_data = market_data
        self._universe = universe
        self._benchmark_symbol = benchmark_symbol
        self._range_start = range_start
        self._range_end = range_end
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

    async def feature_rows(self, symbol: str) -> tuple[FeatureRow, ...]:
        await self._load_benchmark()
        bars = await self._confirmed(symbol)
        self._hashed.extend((symbol, item) for item in bars)
        by_date = {item.bar.trading_date: item.bar for item in bars}
        # 벤치마크와 종목이 모두 있는 날짜만 쓴다. 한쪽이 없으면 시장 특징이 어긋난다.
        shared = tuple(day for day in self._dates if day in by_date)
        if not shared:
            return ()
        return feature_rows(
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
