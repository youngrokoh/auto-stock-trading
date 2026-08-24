"""ETF 모멘텀 자산배분 유니버스(사용자 승인 2026-08-24).

유니버스를 코드 상수로 둔다. 이름으로 분류하지 않고 **추적배수 1.00 + 자산군**으로 고른 결과이며,
거래 안전 정책 §1이 레버리지·인버스 신규 매수를 금지하므로 그 조건이 유니버스에 박혀 있어야 한다.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import final

import anyio

from auto_stock_trading.application.stock_universe import UniverseBarBackfill
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.domain.strategies.etf_allocation import (
    ALLOCATION_UNIVERSE,
    ALLOCATION_WINDOW_START,
    AssetClass,
    allocation_symbols,
)


def test_the_universe_is_the_six_approved_symbols() -> None:
    assert allocation_symbols() == (
        "069500",
        "133690",
        "357870",
        "360750",
        "411060",
        "453850",
    )


def test_every_asset_class_appears_exactly_once() -> None:
    """자산배분은 자산군이 서로 다를 때 의미가 생긴다. 같은 자산군이 둘이면 배분이 아니다."""
    classes = [entry.asset_class for entry in ALLOCATION_UNIVERSE]

    assert len(classes) == len(set(classes))
    assert set(classes) == set(AssetClass)


def test_no_entry_is_leveraged_or_inverse() -> None:
    """정책 §1: 레버리지·인버스 ETF 신규 매수 금지. 추적배수로 판정한다(이름이 아니라)."""
    assert all(entry.tracking_multiple == 1 for entry in ALLOCATION_UNIVERSE)


def test_the_window_start_is_the_latest_listing_date() -> None:
    """공통 구간은 가장 늦게 상장된 자산이 정한다. 그 앞은 자산배분이 성립하지 않는다."""
    latest = max(entry.listed_on for entry in ALLOCATION_UNIVERSE)

    assert latest == ALLOCATION_WINDOW_START
    assert date(2023, 3, 14) == ALLOCATION_WINDOW_START


def test_the_backfill_targets_etfs_not_stocks() -> None:
    """상품유형을 잘못 주면 같은 종목코드로 다른 상품을 조회한다. 기본값에 기대지 않는다."""

    @final
    @dataclass
    class FakeCollector:
        targets: list[InstrumentTarget] = field(default_factory=list)

        async def collect(
            self,
            target: InstrumentTarget,
            start_date: date,
            end_date: date,
            started_at: datetime,
        ) -> object:
            _ = (start_date, end_date, started_at)
            self.targets.append(target)
            return object()

    @final
    class FakeUniverse:
        async def universe_symbols(self) -> tuple[str, ...]:
            return allocation_symbols()

    async def scenario() -> None:
        collector = FakeCollector()
        backfill = UniverseBarBackfill(
            universe=FakeUniverse(),
            collector=collector,
            product_type=ProductType.ETF,
        )

        result = await backfill.run(
            ALLOCATION_WINDOW_START,
            date(2023, 3, 20),
            datetime(2026, 8, 24, tzinfo=UTC),
        )

        assert result.symbols == 6
        assert {target.product_type for target in collector.targets} == {ProductType.ETF}
        assert {target.symbol for target in collector.targets} == set(allocation_symbols())

    anyio.run(scenario)
