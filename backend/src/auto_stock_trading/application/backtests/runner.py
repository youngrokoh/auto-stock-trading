import hashlib
import json
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from functools import partial
from typing import TYPE_CHECKING, Final, Protocol
from uuid import uuid4

from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionRange,
    CalendarVerificationState,
    MarketSessionStatus,
    calendar_session_status,
    calendar_verification_state,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionRange,
    CorporateActionType,
)
from auto_stock_trading.domain.market_data.models import BarFinality
from auto_stock_trading.domain.strategies.backtest import (
    ENGINE_ALGORITHM_VERSION,
    BacktestError,
    BacktestFailure,
    BacktestInputs,
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    EquityPoint,
    ExecutionBar,
    run_backtest,
)
from auto_stock_trading.domain.strategies.costs import (
    KrxMarket,
    UncoveredCostDateError,
    cost_rule_versions_for_window,
)
from auto_stock_trading.domain.strategies.ma_rsi import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    ma_rsi_signals,
)
from auto_stock_trading.domain.strategies.records import BacktestRunRecord

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from auto_stock_trading.domain.market_data.adjustment_datasets import (
        AdjustedBarRecord,
        AdjustmentDatasetRecord,
    )
    from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
    from auto_stock_trading.domain.market_data.calendar import MarketCalendarRecord
    from auto_stock_trading.domain.market_data.corporate_actions import (
        VersionedCorporateAction,
    )
    from auto_stock_trading.domain.market_data.models import (
        Instrument,
        VersionedDailyBar,
    )
    from auto_stock_trading.domain.strategies.ma_rsi import MaRsiParameters

_COUNTRY: Final = "KR"
_EXCHANGE: Final = "XKRX"
_CASH_ACTION_TYPES: Final = frozenset(
    (CorporateActionType.CASH_DIVIDEND, CorporateActionType.ETF_DISTRIBUTION)
)


class BacktestCalendar(Protocol):
    async def sessions(
        self,
        query: CalendarSessionRange,
    ) -> tuple[MarketCalendarRecord, ...]: ...


class BacktestMarketData(Protocol):
    async def instrument(self, symbol: str) -> Instrument | None: ...

    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[VersionedDailyBar, ...]: ...


class BacktestAdjustedPrices(Protocol):
    async def read_latest_published(
        self,
        symbol: str,
        method: AdjustmentMethod,
    ) -> AdjustmentDatasetRecord | None: ...

    async def read_adjusted_bars(self, dataset_id: UUID) -> tuple[AdjustedBarRecord, ...]: ...


class BacktestCorporateActions(Protocol):
    async def read_current(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]: ...


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    symbol: str
    benchmark_symbol: str
    range_start: date
    range_end: date
    initial_cash: Decimal
    signal_method: AdjustmentMethod
    parameters: MaRsiParameters


class BacktestStore(Protocol):
    async def save_run(
        self,
        record: BacktestRunRecord,
        trades: tuple[BacktestTrade, ...],
        equity: tuple[EquityPoint, ...],
    ) -> None: ...


def canonical_parameters_json(parameters: MaRsiParameters) -> str:
    return json.dumps(
        {
            "long_period": parameters.long_period,
            "rsi_overbought": str(parameters.rsi_overbought),
            "rsi_period": parameters.rsi_period,
            "short_period": parameters.short_period,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _bar_version_hash(bars: tuple[VersionedDailyBar, ...]) -> str:
    lines = "\n".join(
        f"{item.bar.trading_date.isoformat()}:{item.version}"
        for item in sorted(bars, key=lambda item: item.bar.trading_date)
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _action_version_hash(
    actions: tuple[tuple[date, VersionedCorporateAction], ...],
) -> str:
    lines = "\n".join(
        f"{ex_date.isoformat()}:{item.action_key}:{item.version}"
        for ex_date, item in sorted(
            actions,
            key=lambda entry: (entry[0], str(entry[1].action_key)),
        )
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _LoadedInputs:
    engine_inputs: BacktestInputs
    input_bar_version_hash: str
    action_version_hash: str
    signal_dataset_id: UUID
    benchmark_dataset_id: UUID


@dataclass(frozen=True, slots=True)
class BacktestRunner:
    calendar: BacktestCalendar
    market_data: BacktestMarketData
    adjusted_prices: BacktestAdjustedPrices
    corporate_actions: BacktestCorporateActions
    store: BacktestStore

    async def run(self, request: BacktestRequest, now: datetime) -> BacktestRunRecord:
        instrument = await self.market_data.instrument(request.symbol)
        if instrument is None:
            msg = f"unknown instrument {request.symbol}"
            raise LookupError(msg)
        base_record = BacktestRunRecord(
            run_id=uuid4(),
            strategy_name=STRATEGY_NAME,
            strategy_version=STRATEGY_VERSION,
            parameters_json=canonical_parameters_json(request.parameters),
            symbol=request.symbol,
            benchmark_symbol=request.benchmark_symbol,
            range_start=request.range_start,
            range_end=request.range_end,
            initial_cash=request.initial_cash,
            signal_method=request.signal_method.value,
            engine_version=ENGINE_ALGORITHM_VERSION,
            cost_rule_versions="[]",
            input_bar_version_hash="",
            action_version_hash="",
            signal_dataset_id=None,
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
            return await self._save_failed(
                base_record,
                BacktestFailure.UNCOVERED_COST_DATE.value,
                str(error),
            )
        try:
            loaded = await self._load_inputs(request, instrument)
        except BacktestError as error:
            record = _with_lineage(base_record, cost_rule_versions=cost_rule_versions)
            return await self._save_failed(record, error.failure.value, error.detail)
        record = _with_lineage(
            base_record,
            cost_rule_versions=cost_rule_versions,
            hashes=(loaded.input_bar_version_hash, loaded.action_version_hash),
            dataset_ids=(loaded.signal_dataset_id, loaded.benchmark_dataset_id),
        )
        signal_fn = partial(ma_rsi_signals, parameters=request.parameters)
        try:
            result = run_backtest(loaded.engine_inputs, signal_fn)
        except BacktestError as error:
            return await self._save_failed(record, error.failure.value, error.detail)
        return await self._save_completed(record, result)

    async def _save_failed(
        self,
        record: BacktestRunRecord,
        failure_code: str,
        detail: str,
    ) -> BacktestRunRecord:
        _ = detail
        failed = _replace_status(record, status="failed", failure_code=failure_code)
        await self.store.save_run(failed, (), ())
        return failed

    async def _save_completed(
        self,
        record: BacktestRunRecord,
        result: BacktestResult,
    ) -> BacktestRunRecord:
        completed = _replace_status(
            record,
            status="completed",
            failure_code=None,
            metrics=result.metrics,
        )
        await self.store.save_run(completed, result.trades, result.equity_curve)
        return completed

    async def _load_inputs(
        self,
        request: BacktestRequest,
        instrument: Instrument,
    ) -> _LoadedInputs:
        trading_dates = await self._trading_dates(request)
        bars = await self._confirmed_bars(request, trading_dates)
        signal_dataset, signal_closes = await self._adjusted_closes(
            request.symbol,
            request.signal_method,
            request,
            trading_dates,
        )
        benchmark_dataset, benchmark_closes = await self._adjusted_closes(
            request.benchmark_symbol,
            request.signal_method,
            request,
            trading_dates,
        )
        cash_actions = await self._cash_actions(request)
        dividends: dict[date, Decimal] = {}
        for ex_date, item in cash_actions:
            amount = item.action.cash_amount
            if amount is not None:
                dividends[ex_date] = dividends.get(ex_date, Decimal(0)) + amount
        engine_inputs = BacktestInputs(
            trading_dates=trading_dates,
            execution_bars={
                item.bar.trading_date: ExecutionBar(
                    open_price=item.bar.open_price,
                    close_price=item.bar.close_price,
                )
                for item in bars
            },
            signal_closes=signal_closes,
            benchmark_closes=benchmark_closes,
            dividends=dividends,
            product_type=instrument.product_type,
            market=KrxMarket.KOSPI,
            initial_cash=request.initial_cash,
        )
        return _LoadedInputs(
            engine_inputs=engine_inputs,
            input_bar_version_hash=_bar_version_hash(bars),
            action_version_hash=_action_version_hash(cash_actions),
            signal_dataset_id=signal_dataset.dataset_id,
            benchmark_dataset_id=benchmark_dataset.dataset_id,
        )

    async def _trading_dates(self, request: BacktestRequest) -> tuple[date, ...]:
        records = await self.calendar.sessions(
            CalendarSessionRange(
                _COUNTRY,
                _EXCHANGE,
                request.range_start,
                request.range_end,
            )
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
        trading_dates: list[date] = []
        for record in sorted(records, key=lambda item: item.session.key.trading_date):
            state = calendar_verification_state(record.verification)
            if state is CalendarVerificationState.CONFLICT:
                conflict_date = record.session.key.trading_date.isoformat()
                raise BacktestError(
                    BacktestFailure.MISSING_CALENDAR_COVERAGE,
                    f"conflicting calendar session at {conflict_date}",
                )
            if calendar_session_status(record.session) is not MarketSessionStatus.CLOSED:
                trading_dates.append(record.session.key.trading_date)
        if not trading_dates:
            raise BacktestError(
                BacktestFailure.MISSING_CALENDAR_COVERAGE,
                "no trading days in the requested window",
            )
        return tuple(trading_dates)

    async def _confirmed_bars(
        self,
        request: BacktestRequest,
        trading_dates: tuple[date, ...],
    ) -> tuple[VersionedDailyBar, ...]:
        bars = await self.market_data.daily_bars(
            request.symbol,
            request.range_start,
            request.range_end,
        )
        confirmed = {
            item.bar.trading_date: item
            for item in bars
            if item.finality is BarFinality.CONFIRMED and item.superseded_at is None
        }
        for trading_date in trading_dates:
            if trading_date not in confirmed:
                raise BacktestError(
                    BacktestFailure.MISSING_CONFIRMED_BAR,
                    f"no confirmed bar for {trading_date.isoformat()}",
                )
        return tuple(confirmed[trading_date] for trading_date in trading_dates)

    async def _adjusted_closes(
        self,
        symbol: str,
        method: AdjustmentMethod,
        request: BacktestRequest,
        trading_dates: tuple[date, ...],
    ) -> tuple[AdjustmentDatasetRecord, tuple[Decimal, ...]]:
        dataset = await self.adjusted_prices.read_latest_published(symbol, method)
        if (
            dataset is None
            or dataset.range_start > trading_dates[0]
            or dataset.price_cutoff_date < trading_dates[-1]
        ):
            window = f"{request.range_start.isoformat()}~{request.range_end.isoformat()}"
            raise BacktestError(
                BacktestFailure.MISSING_ADJUSTED_DATASET,
                f"no published {method.value} dataset covers {symbol} {window}",
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
        return dataset, tuple(closes)

    async def _cash_actions(
        self,
        request: BacktestRequest,
    ) -> tuple[tuple[date, VersionedCorporateAction], ...]:
        actions = await self.corporate_actions.read_current(
            CorporateActionRange(request.symbol, request.range_start, request.range_end)
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


def _with_lineage(
    record: BacktestRunRecord,
    *,
    cost_rule_versions: str,
    hashes: tuple[str, str] = ("", ""),
    dataset_ids: tuple[UUID | None, UUID | None] = (None, None),
) -> BacktestRunRecord:
    return replace(
        record,
        cost_rule_versions=cost_rule_versions,
        input_bar_version_hash=hashes[0],
        action_version_hash=hashes[1],
        signal_dataset_id=dataset_ids[0],
        benchmark_dataset_id=dataset_ids[1],
    )


def _replace_status(
    record: BacktestRunRecord,
    *,
    status: str,
    failure_code: str | None,
    metrics: BacktestMetrics | None = None,
) -> BacktestRunRecord:
    return replace(record, status=status, failure_code=failure_code, metrics=metrics)
