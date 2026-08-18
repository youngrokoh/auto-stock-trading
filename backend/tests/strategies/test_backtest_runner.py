import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import anyio
import pytest

from auto_stock_trading.application.backtests.runner import (
    BacktestRequest,
    BacktestRunner,
)
from auto_stock_trading.domain.market_data.adjustment_datasets import (
    AdjustedBarRecord,
    AdjustmentDatasetRecord,
)
from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarSource,
    ClosedMarketSession,
    ConfirmedVerification,
    MarketCalendarRecord,
    MarketSessionType,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    TimePrecision,
    VersionedCorporateAction,
)
from auto_stock_trading.domain.market_data.models import (
    BarFinality,
    DailyBar,
    Instrument,
    ProductType,
    VersionedDailyBar,
)
from auto_stock_trading.domain.strategies.ma_rsi import MaRsiParameters

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.calendar import CalendarSessionRange
    from auto_stock_trading.domain.market_data.corporate_actions import CorporateActionRange
    from auto_stock_trading.domain.strategies.backtest import BacktestTrade, EquityPoint
    from auto_stock_trading.domain.strategies.records import BacktestRunRecord

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_NOW: Final = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)
_RANGE_START: Final = date(2026, 8, 3)
_RANGE_END: Final = date(2026, 8, 12)
_CLOSED_DATES: Final = frozenset((date(2026, 8, 8), date(2026, 8, 9)))
_TRADING_DATES: Final = tuple(
    _RANGE_START + timedelta(days=offset)
    for offset in range((_RANGE_END - _RANGE_START).days + 1)
    if _RANGE_START + timedelta(days=offset) not in _CLOSED_DATES
)
_CLOSES: Final = tuple(
    Decimal(value) for value in (10000, 9000, 8000, 9000, 12000, 13000, 12000, 9000)
)
_OPENS: Final = tuple(
    Decimal(value) for value in (9900, 9100, 8100, 8900, 11800, 12800, 12200, 9100)
)
_PARAMETERS: Final = MaRsiParameters(
    short_period=2,
    long_period=3,
    rsi_period=2,
    rsi_overbought=Decimal(90),
)
_SYMBOL: Final = "005930"
_BENCHMARK: Final = "069500"


def _request() -> BacktestRequest:
    return BacktestRequest(
        symbol=_SYMBOL,
        benchmark_symbol=_BENCHMARK,
        range_start=_RANGE_START,
        range_end=_RANGE_END,
        initial_cash=Decimal(1_000_000),
        signal_method=AdjustmentMethod.TOTAL_RETURN,
        parameters=_PARAMETERS,
    )


def _calendar_record(trading_date: date) -> MarketCalendarRecord:
    key = CalendarSessionKey("KR", "XKRX", trading_date, MarketSessionType.REGULAR)
    if trading_date in _CLOSED_DATES:
        session = ClosedMarketSession(key, "휴장")
        verification = PendingVerification()
    else:
        session = OpenMarketSession(
            key,
            SessionWindow(
                datetime.combine(trading_date, time(9, 0), _SEOUL),
                datetime.combine(trading_date, time(15, 30), _SEOUL),
            ),
        )
        verification = ConfirmedVerification(_NOW)
    return MarketCalendarRecord(
        id=uuid4(),
        session=session,
        exchange_timezone="Asia/Seoul",
        source=CalendarSource("KRX", "https://example.test/calendar", date(2026, 1, 1)),
        received_at=_NOW,
        verification=verification,
        version=1,
        valid_from=_NOW,
        superseded_at=None,
        raw_response_id=uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _versioned_bar(symbol: str, trading_date: date, index: int) -> VersionedDailyBar:
    return VersionedDailyBar(
        bar=DailyBar(
            symbol=symbol,
            trading_date=trading_date,
            open_price=_OPENS[index],
            high_price=max(_OPENS[index], _CLOSES[index]),
            low_price=min(_OPENS[index], _CLOSES[index]),
            close_price=_CLOSES[index],
            volume=1000,
            trading_value=Decimal(1_000_000),
            adjusted=False,
            correction_code=None,
            split_ratio=None,
            source="KIS",
            received_at=_NOW,
        ),
        finality=BarFinality.CONFIRMED,
        confirmed_at=_NOW,
        version=1,
        valid_from=_NOW,
        superseded_at=None,
    )


def _instrument(symbol: str, product_type: ProductType) -> Instrument:
    return Instrument(
        country="KR",
        exchange="KRX",
        symbol=symbol,
        product_type=product_type,
        currency="KRW",
        name="테스트 종목",
        english_name=None,
        listed_on=None,
        delisted_on=None,
        trading_status="normal",
        source="KIS",
        source_as_of=date(2026, 8, 18),
    )


def _dataset(symbol: str, method: AdjustmentMethod) -> AdjustmentDatasetRecord:
    return AdjustmentDatasetRecord(
        dataset_id=uuid4(),
        symbol=symbol,
        method=method,
        interval="1d",
        range_start=date(2025, 1, 2),
        price_cutoff_date=date(2026, 8, 17),
        knowledge_cutoff_at=_NOW,
        algorithm_version="adjust-1",
        input_bar_version_hash="a" * 64,
        action_version_hash="b" * 64,
        status="published",
        generated_at=_NOW,
        superseded_at=None,
        failure_code=None,
    )


def _adjusted_bars(dataset_id: UUID) -> tuple[AdjustedBarRecord, ...]:
    return tuple(
        AdjustedBarRecord(
            dataset_id=dataset_id,
            source_bar_id=uuid4(),
            trading_date=trading_date,
            open_price=_OPENS[index],
            high_price=max(_OPENS[index], _CLOSES[index]),
            low_price=min(_OPENS[index], _CLOSES[index]),
            close_price=_CLOSES[index],
            volume=1000,
            trading_value=Decimal(1_000_000),
            price_factor=Decimal(1),
            volume_factor=Decimal(1),
            source="KIS",
            source_bar_version=1,
        )
        for index, trading_date in enumerate(_TRADING_DATES)
    )


def _distribution(
    ex_date: date,
    *,
    quality: CorporateActionQuality = CorporateActionQuality.VERIFIED,
    lifecycle: CorporateActionLifecycle = CorporateActionLifecycle.CONFIRMED,
    action_key: UUID | None = None,
) -> VersionedCorporateAction:
    return VersionedCorporateAction(
        action=CorporateAction(
            action_type=CorporateActionType.CASH_DIVIDEND,
            lifecycle=lifecycle,
            quality=quality,
            announced_at=None,
            announcement_date=date(2026, 7, 1),
            time_precision=TimePrecision.DATE,
            ex_date=ex_date,
            effective_date=None,
            record_date=None,
            payment_date=None,
            share_multiplier=None,
            cash_amount=Decimal(50),
            currency="KRW",
            subscription_price=None,
            related_instrument_id=None,
            source="DART",
            source_event_id=f"event-{ex_date.isoformat()}-{quality}",
            source_reference="https://example.test/action",
            available_at=_NOW,
            received_at=_NOW,
        ),
        corporate_action_id=uuid4(),
        action_key=action_key or UUID("00000000-0000-0000-0000-00000000aaaa"),
        version=1,
        valid_from=_NOW,
        superseded_at=None,
    )


@dataclass
class FakeCalendar:
    records: tuple[MarketCalendarRecord, ...]

    async def sessions(self, query: CalendarSessionRange) -> tuple[MarketCalendarRecord, ...]:
        return tuple(
            record
            for record in self.records
            if query.start_date <= _record_date(record) <= query.end_date
        )


def _record_date(record: MarketCalendarRecord) -> date:
    return record.session.key.trading_date


@dataclass
class FakeMarketData:
    instruments_by_symbol: dict[str, Instrument]
    bars_by_symbol: dict[str, tuple[VersionedDailyBar, ...]]

    async def instrument(self, symbol: str) -> Instrument | None:
        return self.instruments_by_symbol.get(symbol)

    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[VersionedDailyBar, ...]:
        bars = self.bars_by_symbol.get(symbol, ())
        return tuple(
            item
            for item in bars
            if (start_date is None or item.bar.trading_date >= start_date)
            and (end_date is None or item.bar.trading_date <= end_date)
        )


@dataclass
class FakeAdjustedPrices:
    datasets: dict[tuple[str, AdjustmentMethod], AdjustmentDatasetRecord]
    bars: dict[UUID, tuple[AdjustedBarRecord, ...]]

    async def read_latest_published(
        self,
        symbol: str,
        method: AdjustmentMethod,
    ) -> AdjustmentDatasetRecord | None:
        return self.datasets.get((symbol, method))

    async def read_adjusted_bars(self, dataset_id: UUID) -> tuple[AdjustedBarRecord, ...]:
        return self.bars.get(dataset_id, ())


@dataclass
class FakeCorporateActions:
    actions: tuple[VersionedCorporateAction, ...] = ()

    async def read_current(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]:
        _ = query
        return self.actions


@dataclass
class FakeStore:
    saved: list[tuple[BacktestRunRecord, tuple[BacktestTrade, ...], tuple[EquityPoint, ...]]] = (
        field(default_factory=list)
    )

    async def save_run(
        self,
        record: BacktestRunRecord,
        trades: tuple[BacktestTrade, ...],
        equity: tuple[EquityPoint, ...],
    ) -> None:
        self.saved.append((record, trades, equity))


def _runner(
    *,
    actions: tuple[VersionedCorporateAction, ...] = (),
    drop_bar_date: date | None = None,
    drop_calendar_date: date | None = None,
    without_signal_dataset: bool = False,
) -> tuple[BacktestRunner, FakeStore]:
    all_days = tuple(
        _RANGE_START + timedelta(days=offset)
        for offset in range((_RANGE_END - _RANGE_START).days + 1)
    )
    calendar_records = tuple(_calendar_record(day) for day in all_days if day != drop_calendar_date)
    bars = tuple(
        _versioned_bar(_SYMBOL, trading_date, index)
        for index, trading_date in enumerate(_TRADING_DATES)
        if trading_date != drop_bar_date
    )
    signal_dataset = _dataset(_SYMBOL, AdjustmentMethod.TOTAL_RETURN)
    benchmark_dataset = _dataset(_BENCHMARK, AdjustmentMethod.TOTAL_RETURN)
    datasets = {
        (_BENCHMARK, AdjustmentMethod.TOTAL_RETURN): benchmark_dataset,
    }
    if not without_signal_dataset:
        datasets[(_SYMBOL, AdjustmentMethod.TOTAL_RETURN)] = signal_dataset
    store = FakeStore()
    runner = BacktestRunner(
        calendar=FakeCalendar(calendar_records),
        market_data=FakeMarketData(
            instruments_by_symbol={_SYMBOL: _instrument(_SYMBOL, ProductType.STOCK)},
            bars_by_symbol={_SYMBOL: bars},
        ),
        adjusted_prices=FakeAdjustedPrices(
            datasets=datasets,
            bars={
                signal_dataset.dataset_id: _adjusted_bars(signal_dataset.dataset_id),
                benchmark_dataset.dataset_id: _adjusted_bars(benchmark_dataset.dataset_id),
            },
        ),
        corporate_actions=FakeCorporateActions(actions),
        store=store,
    )
    return runner, store


def test_runner_completes_and_persists_lineage() -> None:
    runner, store = _runner()

    record = anyio.run(runner.run, _request(), _NOW)

    assert record.status == "completed"
    assert record.failure_code is None
    assert record.strategy_name == "ma-rsi"
    assert record.engine_version == "backtest-1"
    assert (
        record.parameters_json
        == '{"long_period":3,"rsi_overbought":"90","rsi_period":2,"short_period":2}'
    )
    assert record.cost_rule_versions == '["research-krx-2026"]'
    metrics = record.metrics
    assert metrics is not None
    assert metrics.total_return_pct == Decimal("-5.10")
    assert metrics.benchmark_return_pct == Decimal("-10.00")
    assert metrics.trade_count == 2

    expected_bar_lines = "\n".join(
        f"{trading_date.isoformat()}:1" for trading_date in _TRADING_DATES
    )
    assert (
        record.input_bar_version_hash
        == hashlib.sha256(expected_bar_lines.encode("utf-8")).hexdigest()
    )
    assert record.action_version_hash == hashlib.sha256(b"").hexdigest()
    assert record.signal_dataset_id is not None
    assert record.benchmark_dataset_id is not None

    ((saved_record, trades, equity),) = store.saved
    assert saved_record == record
    assert len(trades) == 3
    assert len(equity) == len(_TRADING_DATES)


def test_runner_applies_only_verified_active_cash_actions() -> None:
    ex_date = _TRADING_DATES[6]
    actions = (
        _distribution(ex_date),
        _distribution(
            ex_date,
            quality=CorporateActionQuality.PENDING,
            action_key=UUID("00000000-0000-0000-0000-00000000bbbb"),
        ),
        _distribution(
            ex_date,
            lifecycle=CorporateActionLifecycle.CANCELLED,
            action_key=UUID("00000000-0000-0000-0000-00000000cccc"),
        ),
    )
    runner, store = _runner(actions=actions)

    record = anyio.run(runner.run, _request(), _NOW)

    assert record.status == "completed"
    expected_action_lines = f"{ex_date.isoformat()}:00000000-0000-0000-0000-00000000aaaa:1"
    assert (
        record.action_version_hash
        == hashlib.sha256(expected_action_lines.encode("utf-8")).hexdigest()
    )
    ((_, _, equity),) = store.saved
    # 직전 거래일 보유 78주 × 50원이 락일 현금으로 반영된다.
    assert equity[6].nav == Decimal(948_959) + Decimal(3_900)


def test_runner_records_failed_run_when_dataset_is_missing() -> None:
    runner, store = _runner(without_signal_dataset=True)

    record = anyio.run(runner.run, _request(), _NOW)

    assert record.status == "failed"
    assert record.failure_code == "missing_adjusted_dataset"
    assert record.metrics is None
    ((saved_record, trades, equity),) = store.saved
    assert saved_record == record
    assert trades == ()
    assert equity == ()


def test_runner_records_failed_run_when_bar_is_missing() -> None:
    runner, _ = _runner(drop_bar_date=_TRADING_DATES[3])

    record = anyio.run(runner.run, _request(), _NOW)

    assert record.status == "failed"
    assert record.failure_code == "missing_confirmed_bar"


def test_runner_records_failed_run_when_calendar_has_gaps() -> None:
    runner, _ = _runner(drop_calendar_date=date(2026, 8, 5))

    record = anyio.run(runner.run, _request(), _NOW)

    assert record.status == "failed"
    assert record.failure_code == "missing_calendar_coverage"


def test_runner_is_deterministic_for_identical_inputs() -> None:
    runner, _ = _runner()
    first = anyio.run(runner.run, _request(), _NOW)
    second = anyio.run(runner.run, _request(), _NOW)

    assert replace(first, run_id=second.run_id) == second


def test_runner_rejects_unknown_instrument() -> None:
    runner, _ = _runner()
    request = BacktestRequest(
        symbol="000000",
        benchmark_symbol=_BENCHMARK,
        range_start=_RANGE_START,
        range_end=_RANGE_END,
        initial_cash=Decimal(1_000_000),
        signal_method=AdjustmentMethod.TOTAL_RETURN,
        parameters=_PARAMETERS,
    )
    with pytest.raises(LookupError):
        _ = anyio.run(runner.run, request, _NOW)
