"""다종목 백테스트 실행(계약 v2). 단일 종목 러너는 그대로 두고 별 경로로 조립한다.

단일 종목 러너는 모든 거래일에 확정 일봉이 있어야 실행한다. 다종목은 그럴 수 없다 —
신규 상장·거래정지로 종목마다 커버리지가 다르다. 없는 봉은 그 회차에서 해당 종목을
후보·체결 대상에서 빼는 방식으로 처리하고, 빠진 사실은 체결 기록에 남긴다.
"""

import json
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Protocol
from uuid import uuid4

from auto_stock_trading.application.backtests.lineage import (
    action_version_hash,
    symbol_bar_version_hash,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionRange,
    calendar_session_status,
    calendar_verification_state,
)
from auto_stock_trading.domain.market_data.calendar_models import (
    CalendarVerificationState,
    MarketSessionStatus,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionRange,
    CorporateActionType,
)
from auto_stock_trading.domain.market_data.models import BarFinality, ProductType
from auto_stock_trading.domain.strategies.backtest import (
    BacktestError,
    BacktestFailure,
    ExecutionBar,
)
from auto_stock_trading.domain.strategies.costs import (
    KrxMarket,
    UncoveredCostDateError,
    cost_rule_versions_for_window,
)
from auto_stock_trading.domain.strategies.portfolio_backtest import (
    PORTFOLIO_ENGINE_VERSION,
    PortfolioInputs,
    run_portfolio_backtest,
)
from auto_stock_trading.domain.strategies.ranking import SymbolSeries, rebalance_dates
from auto_stock_trading.domain.strategies.records import PortfolioRunRecord

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime
    from uuid import UUID

    from auto_stock_trading.application.backtests.runner import (
        BacktestAdjustedPrices,
        BacktestCalendar,
        BacktestCorporateActions,
        BacktestMarketData,
    )
    from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
    from auto_stock_trading.domain.market_data.corporate_actions import (
        VersionedCorporateAction,
    )
    from auto_stock_trading.domain.market_data.models import VersionedDailyBar
    from auto_stock_trading.domain.strategies.backtest_metrics import EquityPoint
    from auto_stock_trading.domain.strategies.portfolio_backtest import (
        PortfolioResult,
        PortfolioTrade,
    )
    from auto_stock_trading.domain.strategies.ranking import Rebalance

_COUNTRY: Final = "KR"
_EXCHANGE: Final = "XKRX"
_CASH_ACTION_TYPES: Final = (
    CorporateActionType.CASH_DIVIDEND,
    CorporateActionType.ETF_DISTRIBUTION,
)


@dataclass(frozen=True, slots=True)
class SignalPlan:
    """전략이 만든 회차와 그 전략만의 계보. 재무 요인이 없으면 해시는 비어 있다."""

    rebalances: tuple[Rebalance, ...]
    report_hash: str | None = None


class PortfolioSignalSource(Protocol):
    """전략의 회차 생성기. 순위 규칙 자체는 도메인 순수 함수가 갖는다."""

    def plan(
        self,
        signal_dates: Sequence[date],
        series: Sequence[SymbolSeries],
        trading_dates: Sequence[date],
    ) -> SignalPlan: ...


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """실행 기록에 남는 전략 신원과 회차 생성기."""

    name: str
    version: str
    signal_method: str
    holdings: int
    parameters_json: str
    source: PortfolioSignalSource


@dataclass(frozen=True, slots=True)
class PortfolioRequest:
    universe: tuple[str, ...]
    benchmark_symbol: str
    range_start: date
    range_end: date
    initial_cash: Decimal
    benchmark_method: AdjustmentMethod
    strategy: StrategySpec


@dataclass(frozen=True, slots=True)
class _Loaded:
    inputs: PortfolioInputs
    trading_dates: tuple[date, ...]
    series: tuple[SymbolSeries, ...]
    bar_hash: str
    action_hash: str
    benchmark_dataset_id: UUID


class PortfolioStore(Protocol):
    async def save_portfolio_run(
        self,
        record: PortfolioRunRecord,
        trades: tuple[PortfolioTrade, ...],
        equity: tuple[EquityPoint, ...],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PortfolioRunner:
    calendar: BacktestCalendar
    market_data: BacktestMarketData
    adjusted_prices: BacktestAdjustedPrices
    corporate_actions: BacktestCorporateActions
    store: PortfolioStore

    async def run(self, request: PortfolioRequest, now: datetime) -> PortfolioRunRecord:
        strategy = request.strategy
        base = PortfolioRunRecord(
            run_id=uuid4(),
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            parameters_json=strategy.parameters_json,
            universe=request.universe,
            benchmark_symbol=request.benchmark_symbol,
            range_start=request.range_start,
            range_end=request.range_end,
            initial_cash=request.initial_cash,
            signal_method=strategy.signal_method,
            engine_version=PORTFOLIO_ENGINE_VERSION,
            cost_rule_versions="[]",
            input_bar_version_hash="",
            action_version_hash="",
            input_report_version_hash=None,
            benchmark_dataset_id=None,
            status="failed",
            failure_code=None,
            metrics=None,
            created_at=now,
        )
        try:
            cost_rule_versions = json.dumps(
                list(cost_rule_versions_for_window(request.range_start, request.range_end)),
                separators=(",", ":"),
            )
        except UncoveredCostDateError as error:
            return await self._save_failed(base, BacktestFailure.UNCOVERED_COST_DATE.value, error)
        record = replace(base, cost_rule_versions=cost_rule_versions)
        try:
            loaded = await self._load(request)
            plan = strategy.source.plan(
                rebalance_dates(loaded.trading_dates),
                loaded.series,
                loaded.trading_dates,
            )
        except BacktestError as error:
            return await self._save_failed(record, error.failure.value, error)
        record = replace(
            record,
            input_bar_version_hash=loaded.bar_hash,
            action_version_hash=loaded.action_hash,
            input_report_version_hash=plan.report_hash,
            benchmark_dataset_id=loaded.benchmark_dataset_id,
        )
        result = run_portfolio_backtest(loaded.inputs, plan.rebalances)
        return await self._save_completed(record, result)

    async def _save_failed(
        self,
        record: PortfolioRunRecord,
        failure_code: str,
        error: Exception,
    ) -> PortfolioRunRecord:
        _ = error
        failed = replace(record, status="failed", failure_code=failure_code)
        await self.store.save_portfolio_run(failed, (), ())
        return failed

    async def _save_completed(
        self,
        record: PortfolioRunRecord,
        result: PortfolioResult,
    ) -> PortfolioRunRecord:
        completed = replace(
            record,
            status="completed",
            failure_code=None,
            metrics=result.metrics,
        )
        await self.store.save_portfolio_run(completed, result.trades, result.equity_curve)
        return completed

    async def _trading_dates(self, request: PortfolioRequest) -> tuple[date, ...]:
        records = await self.calendar.sessions(
            CalendarSessionRange(_COUNTRY, _EXCHANGE, request.range_start, request.range_end)
        )
        covered = {record.session.key.trading_date for record in records}
        day_count = (request.range_end - request.range_start).days + 1
        for offset in range(day_count):
            day = request.range_start + timedelta(days=offset)
            if day not in covered:
                raise BacktestError(
                    BacktestFailure.MISSING_CALENDAR_COVERAGE,
                    f"no verified calendar session for {day.isoformat()}",
                )
        dates: list[date] = []
        for record in sorted(records, key=lambda item: item.session.key.trading_date):
            state = calendar_verification_state(record.verification)
            if state is CalendarVerificationState.CONFLICT:
                conflict = record.session.key.trading_date.isoformat()
                raise BacktestError(
                    BacktestFailure.MISSING_CALENDAR_COVERAGE,
                    f"conflicting calendar session at {conflict}",
                )
            if calendar_session_status(record.session) is not MarketSessionStatus.CLOSED:
                dates.append(record.session.key.trading_date)
        if not dates:
            raise BacktestError(
                BacktestFailure.MISSING_CALENDAR_COVERAGE,
                "no trading days in the requested window",
            )
        return tuple(dates)

    async def _confirmed_bars(
        self,
        symbol: str,
        request: PortfolioRequest,
    ) -> tuple[VersionedDailyBar, ...]:
        bars = await self.market_data.daily_bars(symbol, request.range_start, request.range_end)
        return tuple(
            item
            for item in bars
            if item.finality is BarFinality.CONFIRMED and item.superseded_at is None
        )

    async def _cash_actions(
        self,
        symbol: str,
        request: PortfolioRequest,
    ) -> tuple[tuple[date, VersionedCorporateAction], ...]:
        actions = await self.corporate_actions.read_current(
            CorporateActionRange(symbol, request.range_start, request.range_end)
        )
        selected: list[tuple[date, VersionedCorporateAction]] = []
        for item in actions:
            action = item.action
            ex_date = action.ex_date
            if (
                action.action_type in _CASH_ACTION_TYPES
                and action.quality is CorporateActionQuality.VERIFIED
                and action.lifecycle is not CorporateActionLifecycle.CANCELLED
                and ex_date is not None
                and request.range_start <= ex_date <= request.range_end
            ):
                selected.append((ex_date, item))
        return tuple(selected)

    async def _benchmark_closes(
        self,
        request: PortfolioRequest,
        trading_dates: tuple[date, ...],
    ) -> tuple[UUID, tuple[Decimal, ...]]:
        dataset = await self.adjusted_prices.read_latest_published(
            request.benchmark_symbol,
            request.benchmark_method,
        )
        if (
            dataset is None
            or dataset.range_start > trading_dates[0]
            or dataset.price_cutoff_date < trading_dates[-1]
        ):
            window = f"{request.range_start.isoformat()}~{request.range_end.isoformat()}"
            raise BacktestError(
                BacktestFailure.MISSING_ADJUSTED_DATASET,
                f"no published dataset covers {request.benchmark_symbol} {window}",
            )
        adjusted = {
            bar.trading_date: bar.close_price
            for bar in await self.adjusted_prices.read_adjusted_bars(dataset.dataset_id)
        }
        closes: list[Decimal] = []
        for trading_date in trading_dates:
            close_price = adjusted.get(trading_date)
            if close_price is None:
                raise BacktestError(
                    BacktestFailure.MISSING_ADJUSTED_DATASET,
                    f"dataset {dataset.dataset_id} has no bar for {trading_date.isoformat()}",
                )
            closes.append(close_price)
        return dataset.dataset_id, tuple(closes)

    async def _load(self, request: PortfolioRequest) -> _Loaded:
        trading_dates = await self._trading_dates(request)
        benchmark_dataset_id, benchmark_closes = await self._benchmark_closes(
            request,
            trading_dates,
        )
        bars: dict[str, dict[date, ExecutionBar]] = {}
        series: list[SymbolSeries] = []
        hashed_bars: list[tuple[str, VersionedDailyBar]] = []
        dividends: dict[str, dict[date, Decimal]] = {}
        hashed_actions: list[tuple[date, VersionedCorporateAction]] = []
        product_types: dict[str, ProductType] = {}
        for symbol in request.universe:
            confirmed = await self._confirmed_bars(symbol, request)
            if not confirmed:
                continue
            bars[symbol] = {
                item.bar.trading_date: ExecutionBar(
                    open_price=item.bar.open_price,
                    close_price=item.bar.close_price,
                )
                for item in confirmed
            }
            series.append(
                SymbolSeries(
                    symbol=symbol,
                    closes={item.bar.trading_date: item.bar.close_price for item in confirmed},
                )
            )
            hashed_bars.extend((symbol, item) for item in confirmed)
            product_types[symbol] = ProductType.STOCK
            actions = await self._cash_actions(symbol, request)
            hashed_actions.extend(actions)
            per_symbol: dict[date, Decimal] = {}
            for ex_date, item in actions:
                amount = item.action.cash_amount
                if amount is not None:
                    per_symbol[ex_date] = per_symbol.get(ex_date, Decimal(0)) + amount
            if per_symbol:
                dividends[symbol] = per_symbol
        if not series:
            raise BacktestError(
                BacktestFailure.MISSING_CONFIRMED_BAR,
                "no universe symbol has confirmed bars in the window",
            )
        inputs = PortfolioInputs(
            trading_dates=trading_dates,
            bars=bars,
            benchmark_closes=benchmark_closes,
            dividends=dividends,
            product_types=product_types,
            market=KrxMarket.KOSPI,
            initial_cash=request.initial_cash,
            holdings=request.strategy.holdings,
        )
        return _Loaded(
            inputs=inputs,
            trading_dates=trading_dates,
            series=tuple(series),
            bar_hash=symbol_bar_version_hash(tuple(hashed_bars)),
            action_hash=action_version_hash(tuple(hashed_actions)),
            benchmark_dataset_id=benchmark_dataset_id,
        )
