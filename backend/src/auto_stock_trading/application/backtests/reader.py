from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from auto_stock_trading.domain.strategies.backtest_metrics import EquityPoint
    from auto_stock_trading.domain.strategies.records import BacktestRunRecord, BacktestTradeRecord


class BacktestReader(Protocol):
    async def runs(self, limit: int) -> tuple[BacktestRunRecord, ...]: ...

    async def run(self, run_id: UUID) -> BacktestRunRecord | None: ...

    async def trades(self, run_id: UUID) -> tuple[BacktestTradeRecord, ...]: ...

    async def equity(self, run_id: UUID) -> tuple[EquityPoint, ...]: ...

    async def close(self) -> None: ...
