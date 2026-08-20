from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Final, final

import anyio

from auto_stock_trading.application.corporate_actions import UniverseDividendCollection
from auto_stock_trading.domain.market_data.corp_codes import DartCorpCode

_NOW: Final = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
_START: Final = date(2025, 1, 1)
_END: Final = date(2026, 8, 20)


def _code(symbol: str, corp_code: str) -> DartCorpCode:
    return DartCorpCode(
        symbol=symbol,
        corp_code=corp_code,
        corp_name=f"회사{symbol}",
        source="DART",
        received_at=_NOW,
    )


@final
@dataclass
class FakeCodes:
    universe: tuple[str, ...] = ("005930", "000660", "035420")
    known: tuple[DartCorpCode, ...] = (
        _code("005930", "00126380"),
        _code("000660", "00164779"),
    )

    async def universe_symbols(self) -> tuple[str, ...]:
        return self.universe

    async def universe_corp_codes(self) -> tuple[DartCorpCode, ...]:
        return self.known


@final
@dataclass
class FakeDividends:
    observations: int = 3
    failing: tuple[str, ...] = ()
    hanging: tuple[str, ...] = ()
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def collect_symbol(
        self,
        symbol: str,
        corp_code: str,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> int:
        assert (start_date, end_date, now) is not None
        self.calls.append((symbol, corp_code))
        if symbol in self.hanging:
            await anyio.sleep(30)
        if symbol in self.failing:
            raise TimeoutError
        return self.observations


def test_collection_uses_the_corp_code_of_each_universe_symbol() -> None:
    async def run() -> None:
        source = FakeDividends()

        result = await UniverseDividendCollection(codes=FakeCodes(), source=source).run(
            _START,
            _END,
            _NOW,
        )

        assert source.calls == [("005930", "00126380"), ("000660", "00164779")]
        assert (result.symbols, result.observations, result.failed) == (2, 6, 0)

    anyio.run(run)


def test_universe_symbols_without_a_corp_code_are_reported_not_guessed() -> None:
    """매핑이 없는 종목은 배당을 조회할 방법이 없다. 추측하지 않고 사실로 보고한다."""

    async def run() -> None:
        result = await UniverseDividendCollection(
            codes=FakeCodes(),
            source=FakeDividends(),
        ).run(_START, _END, _NOW)

        assert result.missing_corp_codes == ("035420",)

    anyio.run(run)


def test_a_failing_symbol_does_not_stop_the_collection() -> None:
    async def run() -> None:
        source = FakeDividends(failing=("005930",))

        result = await UniverseDividendCollection(codes=FakeCodes(), source=source).run(
            _START,
            _END,
            _NOW,
        )

        assert (result.symbols, result.observations, result.failed) == (2, 3, 1)
        # 어느 종목이 실패했는지 알 수 없으면 운영자가 손을 쓸 수 없다.
        assert result.failed_symbols == ("005930",)
        assert ("000660", "00164779") in source.calls

    anyio.run(run)


def test_a_hung_symbol_is_abandoned_so_the_collection_finishes() -> None:
    async def run() -> None:
        source = FakeDividends(hanging=("005930",))

        result = await UniverseDividendCollection(
            codes=FakeCodes(),
            source=source,
            symbol_timeout_seconds=0.05,
        ).run(_START, _END, _NOW)

        assert (result.observations, result.failed) == (3, 1)

    anyio.run(run)
