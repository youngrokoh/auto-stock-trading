"""모델·평가·중요도 저장(ML 신호 계약 §저장)."""

from decimal import Decimal
from typing import TYPE_CHECKING, final
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.ml_rows import (
    FeatureImportanceRow,
    ModelEvaluationRow,
    ModelRow,
)

if TYPE_CHECKING:
    from uuid import UUID

    from auto_stock_trading.ml.records import (
        FeatureImportanceRecord,
        ModelEvaluationRecord,
        ModelRecord,
    )


@final
class PostgresModelStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresModelStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresModelStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def save_model(
        self,
        record: ModelRecord,
        evaluations: tuple[ModelEvaluationRecord, ...],
        importances: tuple[FeatureImportanceRecord, ...],
    ) -> UUID:
        """모델과 구간 지표·중요도를 한 트랜잭션에 넣는다. 부분 저장을 남기지 않는다."""
        async with self._sessions.begin() as session:
            session.add(
                ModelRow(
                    id=record.model_id,
                    name=record.name,
                    version=record.version,
                    algorithm=record.algorithm,
                    feature_version=record.feature_version,
                    target_definition=record.target_definition,
                    train_start=record.train_start,
                    train_end=record.train_end,
                    embargo_days=record.embargo_days,
                    horizon_days=record.horizon_days,
                    universe_size=record.universe_size,
                    train_sample_count=record.train_sample_count,
                    hyperparameters_json=record.hyperparameters_json,
                    seed=record.seed,
                    artifact=record.artifact,
                    input_bar_version_hash=record.input_bar_version_hash,
                    created_at=record.created_at,
                )
            )
            for item in evaluations:
                session.add(
                    ModelEvaluationRow(
                        id=uuid4(),
                        model_id=record.model_id,
                        fold_index=item.fold_index,
                        valid_start=item.valid_start,
                        valid_end=item.valid_end,
                        sample_count=item.sample_count,
                        metric_name=item.metric_name,
                        metric_value=Decimal(repr(item.metric_value)),
                    )
                )
            for item in importances:
                session.add(
                    FeatureImportanceRow(
                        id=uuid4(),
                        model_id=record.model_id,
                        feature_name=item.feature_name,
                        importance=Decimal(repr(item.importance)),
                    )
                )
        return record.model_id

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
