"""저장된 모델 조회(ML 신호 계약 §저장).

백테스트는 학습하지 않는다. 저장된 산출물만 읽어 추론한다(ADR-0012 결정 3).
"""

from typing import final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.ml_rows import ModelRow
from auto_stock_trading.ml.records import ModelRecord


@final
class PostgresModelReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresModelReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresModelReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def read_model(self, name: str, version: str) -> ModelRecord | None:
        statement = select(ModelRow).where(ModelRow.name == name, ModelRow.version == version)
        async with self._sessions() as session:
            row = (await session.scalars(statement)).one_or_none()
        if row is None:
            return None
        return ModelRecord(
            model_id=row.id,
            name=row.name,
            version=row.version,
            algorithm=row.algorithm,
            feature_version=row.feature_version,
            target_definition=row.target_definition,
            train_start=row.train_start,
            train_end=row.train_end,
            embargo_days=row.embargo_days,
            horizon_days=row.horizon_days,
            out_of_sample_start=row.out_of_sample_start,
            universe_size=row.universe_size,
            train_sample_count=row.train_sample_count,
            hyperparameters_json=row.hyperparameters_json,
            seed=row.seed,
            artifact=row.artifact,
            input_bar_version_hash=row.input_bar_version_hash,
            created_at=row.created_at,
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
