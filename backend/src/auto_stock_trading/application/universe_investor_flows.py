"""유니버스 수급 스윕(수급·공시 계약 §수급).

`stock_universe.py`가 이미 250줄에 가까워 별 모듈로 둔다. 수집·저장 규칙은 `InvestorFlowCollector`가
그대로 갖고 이 층은 대상 선정과 개별 실패 흡수만 한다.

원천이 최근 약 30거래일만 주므로 이력은 첫 수집부터 축적되고 그 이전 공백은 영구적이다. 그래서
한 종목의 실패가 스윕을 멈추면 그날 나머지 종목의 이력이 영구히 빈다 — 실패는 세고 넘어간다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import anyio

from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType

if TYPE_CHECKING:
    from datetime import datetime

# 종목당 상한. 응답이 매달려 HTTP 읽기 타임아웃이 걸리지 않는 경우를 실측했다.
_SYMBOL_TIMEOUT_SECONDS: Final = 60.0


class UniverseSymbols(Protocol):
    async def universe_symbols(self) -> tuple[str, ...]: ...


class FlowCollector(Protocol):
    """수급 수집 한 단위. `InvestorFlowCollector`가 그대로 만족한다."""

    async def collect(self, target: InstrumentTarget, now: datetime) -> object: ...


@dataclass(frozen=True, slots=True)
class FlowSweepResult:
    collected: int
    failed: int
    failed_symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniverseInvestorFlowSweep:
    universe: UniverseSymbols
    collector: FlowCollector
    symbol_timeout_seconds: float = _SYMBOL_TIMEOUT_SECONDS

    async def run(self, now: datetime) -> FlowSweepResult:
        collected = 0
        failed: list[str] = []
        for symbol in await self.universe.universe_symbols():
            try:
                with anyio.fail_after(self.symbol_timeout_seconds):
                    _ = await self.collector.collect(
                        InstrumentTarget(symbol, ProductType.STOCK),
                        now,
                    )
            except Exception:  # noqa: BLE001 — 개별 종목 실패는 스윕을 멈추지 않는다
                failed.append(symbol)
            else:
                collected += 1
        return FlowSweepResult(
            collected=collected,
            failed=len(failed),
            failed_symbols=tuple(failed),
        )
