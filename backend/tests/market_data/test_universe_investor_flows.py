"""유니버스 수급 스윕(수급·공시 계약 §수급). 순수 조립이며 수집 규칙은 수집기가 갖는다.

원천이 최근 약 30거래일만 주므로 이력은 첫 수집부터 축적된다. 그래서 스윕은 한 종목이 실패해도
멈추지 않아야 한다 — 멈추면 그날 나머지 종목의 이력이 영구히 비는 날이 생긴다.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

import anyio

from auto_stock_trading.application.universe_investor_flows import UniverseInvestorFlowSweep

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.models import InstrumentTarget

_NOW = datetime(2026, 8, 23, 6, 0, tzinfo=UTC)


@final
class StubUniverse:
    def __init__(self, symbols: tuple[str, ...]) -> None:
        self._symbols = symbols

    async def universe_symbols(self) -> tuple[str, ...]:
        return self._symbols


@final
class StubCollector:
    """`InvestorFlowCollector`와 같은 모양. 지정한 종목에서만 실패한다."""

    def __init__(
        self,
        failing: frozenset[str] | None = None,
        hanging: str | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._failing = failing or frozenset()
        self._hanging = hanging

    async def collect(self, target: InstrumentTarget, now: datetime) -> object:
        _ = now
        self.calls.append(target.symbol)
        if target.symbol == self._hanging:
            await anyio.sleep(3600)
        if target.symbol in self._failing:
            message = f"collection failed for {target.symbol}"
            raise RuntimeError(message)
        return object()


def test_every_universe_symbol_is_collected() -> None:
    collector = StubCollector()
    sweep = UniverseInvestorFlowSweep(
        universe=StubUniverse(("005930", "000660", "035420")),
        collector=collector,
    )

    result = anyio.run(sweep.run, _NOW)

    assert collector.calls == ["005930", "000660", "035420"]
    assert result.collected == 3
    assert result.failed == 0
    assert result.failed_symbols == ()


def test_one_failure_does_not_stop_the_sweep_and_is_reported() -> None:
    collector = StubCollector(failing=frozenset({"000660"}))
    sweep = UniverseInvestorFlowSweep(
        universe=StubUniverse(("005930", "000660", "035420")),
        collector=collector,
    )

    result = anyio.run(sweep.run, _NOW)

    assert collector.calls == ["005930", "000660", "035420"]
    assert result.collected == 2
    assert result.failed == 1
    # 무엇을 다시 돌릴지 알 수 있어야 한다.
    assert result.failed_symbols == ("000660",)


def test_a_hanging_symbol_is_bounded_and_the_sweep_continues() -> None:
    """실측: KIS 요청이 응답 없이 매달려 HTTP 읽기 타임아웃이 걸리지 않는 경우가 있다."""
    collector = StubCollector(hanging="005930")
    sweep = UniverseInvestorFlowSweep(
        universe=StubUniverse(("005930", "000660")),
        collector=collector,
        symbol_timeout_seconds=0.05,
    )

    result = anyio.run(sweep.run, _NOW)

    assert collector.calls == ["005930", "000660"]
    assert result.collected == 1
    assert result.failed_symbols == ("005930",)


def test_an_empty_universe_collects_nothing() -> None:
    collector = StubCollector()
    sweep = UniverseInvestorFlowSweep(universe=StubUniverse(()), collector=collector)

    result = anyio.run(sweep.run, _NOW)

    assert collector.calls == []
    assert result.collected == 0
    assert result.failed == 0
