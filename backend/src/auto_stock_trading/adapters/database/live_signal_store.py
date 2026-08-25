"""실주문 신호 저장소(ADR-0016 결정 2). 같은 기준일의 신호는 하나다.

재실행이 신호를 덮어쓰지 않는다 — 같은 기준일에 같은 확정 봉으로 다시 계산하면 결과가 같고, 다르다면
그것은 확정 봉이 바뀐 것이므로 조용히 덮어써서는 안 된다. 유일 제약이 두 번째 저장을 흡수한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.strategy_backtest_rows import (
    LiveSignalRow,
    LiveSignalTargetRow,
)
from auto_stock_trading.domain.strategies.ranking import RankedSymbol

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.application.trading.signals import LiveSignal


@dataclass(frozen=True, slots=True)
class StoredSignal:
    """저장된 신호의 신원과 목표. 계획이 계보를 그대로 옮겨 적을 수 있어야 한다."""

    basis_date: date
    rebalance_date: date
    strategy_name: str
    strategy_version: str
    parameters_json: str
    targets: tuple[RankedSymbol, ...]


@final
class PostgresLiveSignalStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresLiveSignalStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresLiveSignalStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def save(self, environment: str, signal: LiveSignal, created_at: datetime) -> bool:
        """저장했으면 True. 같은 기준일이 이미 있으면 False이며 덮어쓰지 않는다."""
        signal_id = uuid4()
        statement = (
            insert(LiveSignalRow)
            .values(
                id=signal_id,
                environment=environment,
                strategy_name=signal.strategy_name,
                strategy_version=signal.strategy_version,
                parameters_json=signal.parameters_json,
                basis_date=signal.basis_date,
                rebalance_date=signal.rebalance_date,
                bar_version_hash=signal.bar_version_hash,
                basis_close_json=json.dumps(
                    {symbol: str(price) for symbol, price in signal.basis_close},
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                created_at=created_at,
            )
            .on_conflict_do_nothing(constraint="uq_live_signal_basis")
            .returning(LiveSignalRow.id)
        )
        async with self._sessions.begin() as session:
            stored = (await session.scalars(statement)).all()
            if not stored:
                return False
            for sequence, target in enumerate(signal.targets, start=1):
                session.add(
                    LiveSignalTargetRow(
                        id=uuid4(),
                        signal_id=signal_id,
                        sequence=sequence,
                        symbol=target.symbol,
                        score=target.score,
                    )
                )
        return True

    async def latest_targets(
        self,
        environment: str,
        strategy_name: str,
    ) -> StoredSignal | None:
        """가장 최근 기준일의 신호. 계획 경로가 이것을 후보로 바꾼다."""
        head = (
            select(LiveSignalRow)
            .where(
                LiveSignalRow.environment == environment,
                LiveSignalRow.strategy_name == strategy_name,
            )
            .order_by(LiveSignalRow.basis_date.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            row = await session.scalar(head)
            if row is None:
                return None
            targets = (
                (
                    await session.execute(
                        select(LiveSignalTargetRow.symbol, LiveSignalTargetRow.score)
                        .where(LiveSignalTargetRow.signal_id == row.id)
                        .order_by(LiveSignalTargetRow.sequence)
                    )
                )
                .tuples()
                .all()
            )
        return StoredSignal(
            basis_date=row.basis_date,
            rebalance_date=row.rebalance_date,
            strategy_name=row.strategy_name,
            strategy_version=row.strategy_version,
            parameters_json=row.parameters_json,
            targets=tuple(RankedSymbol(symbol=symbol, score=score) for symbol, score in targets),
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
