from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import TYPE_CHECKING, Final, final

import anyio

from auto_stock_trading.application.market_data import DailyBarConfirmation
from auto_stock_trading.application.stock_universe import (
    UniverseBarBackfill,
    UniverseBarConfirmation,
)

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.models import InstrumentTarget

_NOW: Final = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
_START: Final = date(2025, 1, 2)
_END: Final = date(2025, 6, 30)


@final
@dataclass
class FakeUniverse:
    symbols: tuple[str, ...] = ("005930", "035420")

    async def universe_symbols(self) -> tuple[str, ...]:
        return self.symbols


@final
@dataclass
class FakeCollector:
    failing: tuple[str, ...] = ()
    hanging: tuple[str, ...] = ()
    calls: list[tuple[str, date, date]] = field(default_factory=list)

    async def collect(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
        started_at: datetime,
    ) -> None:
        assert started_at is not None
        self.calls.append((target.symbol, start_date, end_date))
        if target.symbol in self.hanging:
            await anyio.sleep(30)
        if target.symbol in self.failing:
            raise TimeoutError


def test_the_backfill_splits_the_window_into_chunks_within_the_response_limit() -> None:
    """회당 최대 100봉이라 구간을 나눈다. 나눈 구간은 창을 빠짐없이 덮어야 한다."""

    async def run() -> None:
        collector = FakeCollector()
        backfill = UniverseBarBackfill(
            universe=FakeUniverse(symbols=("005930",)),
            collector=collector,
            chunk_days=60,
        )

        result = await backfill.run(_START, _END, _NOW)

        windows = [(start, end) for _, start, end in collector.calls]
        assert windows[0][0] == _START
        assert windows[-1][1] == _END
        # 구간이 겹치지 않고 하루도 비지 않는다.
        for previous, current in pairwise(windows):
            assert (current[0] - previous[1]).days == 1
        assert all((end - start).days < 60 for start, end in windows)
        assert (result.symbols, result.failed_chunks) == (1, 0)
        assert result.collected_chunks == len(windows)

    anyio.run(run)


def test_every_universe_symbol_is_covered() -> None:
    async def run() -> None:
        collector = FakeCollector()
        backfill = UniverseBarBackfill(
            universe=FakeUniverse(symbols=("005930", "035420", "000660")),
            collector=collector,
            chunk_days=120,
        )

        result = await backfill.run(_START, _END, _NOW)

        assert {symbol for symbol, _, _ in collector.calls} == {"005930", "035420", "000660"}
        assert result.symbols == 3

    anyio.run(run)


def test_a_failing_symbol_does_not_stop_the_backfill() -> None:
    async def run() -> None:
        collector = FakeCollector(failing=("035420",))
        backfill = UniverseBarBackfill(
            universe=FakeUniverse(symbols=("005930", "035420", "000660")),
            collector=collector,
            chunk_days=120,
        )

        result = await backfill.run(_START, _END, _NOW)

        assert result.failed_chunks > 0
        assert result.collected_chunks > 0
        assert "000660" in {symbol for symbol, _, _ in collector.calls}

    anyio.run(run)


def test_a_hung_chunk_is_abandoned_so_the_backfill_finishes() -> None:
    """시세 스윕과 같은 결함 계열: 응답이 매달리면 상한으로 끊고 다음으로 넘어간다."""

    async def run() -> None:
        collector = FakeCollector(hanging=("035420",))
        backfill = UniverseBarBackfill(
            universe=FakeUniverse(symbols=("005930", "035420", "000660")),
            collector=collector,
            chunk_days=200,
            chunk_timeout_seconds=0.05,
        )

        result = await backfill.run(_START, _END, _NOW)

        assert result.failed_chunks == 1
        assert result.collected_chunks == 2
        assert "000660" in {symbol for symbol, _, _ in collector.calls}

    anyio.run(run)


@final
@dataclass
class FakeConfirmer:
    hanging: tuple[str, ...] = ()
    calls: list[str] = field(default_factory=list)

    async def confirm(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> DailyBarConfirmation:
        assert (start_date, end_date, now) is not None
        self.calls.append(target.symbol)
        if target.symbol in self.hanging:
            await anyio.sleep(30)
        return DailyBarConfirmation(confirmed=2, pending=1)


def test_the_confirmation_pass_covers_every_symbol_and_sums_the_counts() -> None:
    async def run() -> None:
        confirmer = FakeConfirmer()
        pass_ = UniverseBarConfirmation(
            universe=FakeUniverse(symbols=("005930", "035420")),
            confirmer=confirmer,
            chunk_days=200,
        )

        result = await pass_.run(_START, _END, _NOW)

        assert confirmer.calls == ["005930", "035420"]
        assert (result.confirmed, result.pending, result.failed_chunks) == (4, 2, 0)

    anyio.run(run)


def test_a_hung_confirmation_is_abandoned_and_counted() -> None:
    async def run() -> None:
        confirmer = FakeConfirmer(hanging=("035420",))
        pass_ = UniverseBarConfirmation(
            universe=FakeUniverse(symbols=("005930", "035420", "000660")),
            confirmer=confirmer,
            chunk_days=200,
            chunk_timeout_seconds=0.05,
        )

        result = await pass_.run(_START, _END, _NOW)

        assert (result.confirmed, result.pending, result.failed_chunks) == (4, 2, 1)

    anyio.run(run)
