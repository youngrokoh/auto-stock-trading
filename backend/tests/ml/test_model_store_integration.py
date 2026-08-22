"""모델 저장소 통합 검증(ML 신호 계약 §저장).

실측 결함(2026-08-22): 모델·평가·중요도를 같은 세션에 add했더니 자식 행이 먼저 flush돼
외래키 위반으로 학습 전체가 실패했다. ORM 관계를 두지 않았으므로 삽입 순서를 SQLAlchemy가
알 수 없다. 실제 PostgreSQL에 넣어보지 않으면 가짜 저장소로는 잡히지 않는 종류의 결함이다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

import anyio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.ml_model_store import PostgresModelStore
from auto_stock_trading.adapters.database.ml_rows import (
    FeatureImportanceRow,
    ModelEvaluationRow,
    ModelRow,
)
from auto_stock_trading.ml.records import (
    FeatureImportanceRecord,
    ModelEvaluationRecord,
    ModelRecord,
)
from auto_stock_trading.settings.runtime import Settings

_NOW: Final = datetime(2026, 8, 22, 4, 0, tzinfo=UTC)
_NAME: Final = "store-integration-test"


def _record(model_id: UUID) -> ModelRecord:
    return ModelRecord(
        model_id=model_id,
        name=_NAME,
        version="1",
        algorithm="ridge",
        feature_version="features-1",
        target_definition="cross_sectional_rank_of_20d_excess_return",
        train_start=date(2020, 1, 2),
        train_end=date(2024, 12, 30),
        embargo_days=20,
        horizon_days=20,
        out_of_sample_start=date(2025, 2, 3),
        universe_size=200,
        train_sample_count=123_456,
        hyperparameters_json='{"alpha":1.0}',
        seed=7,
        artifact='{"format":"ridge-coefficients-1"}',
        input_bar_version_hash="a" * 64,
        created_at=_NOW,
    )


def test_model_metrics_and_importances_are_stored_in_one_transaction() -> None:
    async def run() -> None:
        url = Settings().database_url.get_secret_value()
        engine = create_async_engine(url)
        store = PostgresModelStore.from_url(url)
        model_id = uuid4()
        try:
            saved = await store.save_model(
                _record(model_id),
                (
                    ModelEvaluationRecord(
                        fold_index=1,
                        valid_start=date(2021, 3, 1),
                        valid_end=date(2021, 5, 31),
                        sample_count=1_000,
                        metric_name="rank_ic",
                        metric_value=0.0123,
                    ),
                    ModelEvaluationRecord(
                        fold_index=1,
                        valid_start=date(2021, 3, 1),
                        valid_end=date(2021, 5, 31),
                        sample_count=1_000,
                        metric_name="hit_rate",
                        metric_value=0.5,
                    ),
                ),
                (
                    FeatureImportanceRecord(
                        model_id=model_id,
                        feature_name="vol_60",
                        importance=0.327,
                    ),
                ),
            )
            assert saved == model_id

            async with engine.connect() as connection:
                models = (
                    await connection.execute(select(ModelRow).where(ModelRow.id == model_id))
                ).all()
                metrics = (
                    await connection.execute(
                        select(ModelEvaluationRow.metric_name, ModelEvaluationRow.metric_value)
                        .where(ModelEvaluationRow.model_id == model_id)
                        .order_by(ModelEvaluationRow.metric_name)
                    )
                ).all()
                importances = (
                    await connection.execute(
                        select(
                            FeatureImportanceRow.feature_name,
                            FeatureImportanceRow.importance,
                        ).where(FeatureImportanceRow.model_id == model_id)
                    )
                ).all()
            assert len(models) == 1
            assert [(row[0], row[1]) for row in metrics] == [
                ("hit_rate", Decimal("0.500000")),
                ("rank_ic", Decimal("0.012300")),
            ]
            assert [(row[0], row[1]) for row in importances] == [("vol_60", Decimal("0.32700000"))]
        finally:
            async with engine.begin() as connection:
                _ = await connection.execute(delete(ModelRow).where(ModelRow.id == model_id))
            await engine.dispose()
            await store.close()

    anyio.run(run)
