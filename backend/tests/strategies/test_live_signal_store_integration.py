"""실주문 신호 저장소 통합 테스트. 적용된 스키마에서 확인한다.

핵심은 **같은 기준일의 신호를 덮어쓰지 않는다**는 것이다. 같은 확정 봉으로 다시 계산하면 결과가
같고, 다르다면 확정 봉이 바뀐 것이므로 조용히 덮어써서는 안 된다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import anyio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.live_signal_store import PostgresLiveSignalStore
from auto_stock_trading.adapters.database.strategy_backtest_rows import (
    LiveSignalRow,
    LiveSignalTargetRow,
)
from auto_stock_trading.application.trading.signals import LiveSignal
from auto_stock_trading.domain.strategies.ranking import RankedSymbol
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncConnection

    type SignalScenario = Callable[[PostgresLiveSignalStore, AsyncConnection], Awaitable[None]]

_ENVIRONMENT: Final = "paper"
_NOW: Final = datetime(2026, 8, 25, 0, 30, tzinfo=UTC)
_BASIS: Final = date(2026, 8, 24)
_STRATEGY: Final = "etf-allocation-momentum"


def _signal(*, basis: date = _BASIS, targets: tuple[str, ...] = ("069500", "133690")) -> LiveSignal:
    return LiveSignal(
        strategy_name=_STRATEGY,
        strategy_version="1",
        parameters_json='{"holdings":2,"lookback_days":250}',
        basis_date=basis,
        rebalance_date=date(2026, 7, 31),
        bar_version_hash="a" * 64,
        basis_close=(("069500", Decimal(110060)), ("133690", Decimal(20000))),
        targets=tuple(RankedSymbol(symbol=symbol, score=Decimal("0.5")) for symbol in targets),
    )


async def _run_scenario(scenario: SignalScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        _ = await connection.execute(
            delete(LiveSignalRow).where(LiveSignalRow.environment == _ENVIRONMENT)
        )
        store = PostgresLiveSignalStore.from_connection(connection)
        try:
            await scenario(store, connection)
        finally:
            await store.close()
            await transaction.rollback()
    await engine.dispose()


def test_a_signal_and_its_targets_are_stored_together() -> None:
    async def scenario(store: PostgresLiveSignalStore, connection: AsyncConnection) -> None:
        assert await store.save(_ENVIRONMENT, _signal(), _NOW) is True

        stored = await store.latest_targets(_ENVIRONMENT, _STRATEGY)
        assert stored is not None
        assert stored.basis_date == _BASIS
        assert stored.rebalance_date == date(2026, 7, 31)
        assert [item.symbol for item in stored.targets] == ["069500", "133690"]
        count = await connection.scalar(select(LiveSignalTargetRow.id).limit(1))
        assert count is not None

    anyio.run(_run_scenario, scenario)


def test_the_same_basis_date_is_not_overwritten() -> None:
    """재실행이 신호를 덮어쓰면 계획이 읽는 사실이 조용히 바뀐다."""

    async def scenario(store: PostgresLiveSignalStore, connection: AsyncConnection) -> None:
        _ = connection
        assert await store.save(_ENVIRONMENT, _signal(), _NOW) is True

        assert await store.save(_ENVIRONMENT, _signal(targets=("411060",)), _NOW) is False

        stored = await store.latest_targets(_ENVIRONMENT, _STRATEGY)
        assert stored is not None
        assert [item.symbol for item in stored.targets] == ["069500", "133690"]

    anyio.run(_run_scenario, scenario)


def test_the_latest_basis_date_wins() -> None:
    async def scenario(store: PostgresLiveSignalStore, connection: AsyncConnection) -> None:
        _ = connection
        assert await store.save(_ENVIRONMENT, _signal(basis=date(2026, 8, 21)), _NOW) is True
        assert (
            await store.save(
                _ENVIRONMENT,
                _signal(basis=_BASIS, targets=("411060", "453850")),
                _NOW,
            )
            is True
        )

        stored = await store.latest_targets(_ENVIRONMENT, _STRATEGY)
        assert stored is not None
        assert stored.basis_date == _BASIS
        assert [item.symbol for item in stored.targets] == ["411060", "453850"]

    anyio.run(_run_scenario, scenario)


def test_an_empty_store_returns_nothing() -> None:
    async def scenario(store: PostgresLiveSignalStore, connection: AsyncConnection) -> None:
        _ = connection
        assert await store.latest_targets(_ENVIRONMENT, _STRATEGY) is None

    anyio.run(_run_scenario, scenario)


def test_a_signal_id_is_not_reused_across_targets() -> None:
    """목표 행이 신호에 매달려 있어야 신호를 지울 때 함께 사라진다."""

    async def scenario(store: PostgresLiveSignalStore, connection: AsyncConnection) -> None:
        assert await store.save(_ENVIRONMENT, _signal(), _NOW) is True
        signal_id = await connection.scalar(select(LiveSignalRow.id))
        assert signal_id is not None

        _ = await connection.execute(delete(LiveSignalRow).where(LiveSignalRow.id == signal_id))

        remaining = await connection.scalar(
            select(LiveSignalTargetRow.id).where(LiveSignalTargetRow.signal_id == signal_id)
        )
        assert remaining is None

    anyio.run(_run_scenario, scenario)


def test_saving_uses_a_fresh_identifier_each_time() -> None:
    async def scenario(store: PostgresLiveSignalStore, connection: AsyncConnection) -> None:
        _ = connection
        assert await store.save(_ENVIRONMENT, _signal(basis=date(2026, 8, 20)), _NOW) is True
        assert await store.save(_ENVIRONMENT, _signal(basis=date(2026, 8, 21)), _NOW) is True

        rows = (await connection.execute(select(LiveSignalRow.id))).scalars().all()
        assert len(set(rows)) == len(rows)
        assert uuid4() not in set(rows)

    anyio.run(_run_scenario, scenario)
