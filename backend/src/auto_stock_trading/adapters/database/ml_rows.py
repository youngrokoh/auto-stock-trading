"""`ml` 스키마 행 매핑(리비전 20260822_0025)."""

# SQLAlchemy 매핑이 런타임에 이 타입들을 읽으므로 타입 검사 블록으로 옮기지 않는다.
from datetime import date, datetime  # noqa: TC003
from decimal import Decimal  # noqa: TC003
from typing import final
from uuid import UUID  # noqa: TC003

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from auto_stock_trading.adapters.database.market_data_rows import Base


@final
class ModelRow(Base):
    __tablename__: str = "model"
    __table_args__: tuple[
        CheckConstraint,
        CheckConstraint,
        CheckConstraint,
        CheckConstraint,
        UniqueConstraint,
        Index,
        dict[str, str],
    ] = (
        CheckConstraint("embargo_days >= horizon_days", name="ck_model_embargo_covers_horizon"),
        CheckConstraint(
            "out_of_sample_start IS NULL OR out_of_sample_start > train_end",
            name="ck_model_out_of_sample_after_train",
        ),
        CheckConstraint("train_sample_count > 0", name="ck_model_train_samples_positive"),
        CheckConstraint("train_end >= train_start", name="ck_model_train_window"),
        UniqueConstraint("name", "version", name="uq_model_name_version"),
        Index("ix_model_created_at", "created_at"),
        {"schema": "ml"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(16))
    algorithm: Mapped[str] = mapped_column(String(24))
    feature_version: Mapped[str] = mapped_column(String(24))
    target_definition: Mapped[str] = mapped_column(String(80))
    train_start: Mapped[date] = mapped_column(Date)
    train_end: Mapped[date] = mapped_column(Date)
    embargo_days: Mapped[int] = mapped_column(Integer)
    horizon_days: Mapped[int] = mapped_column(Integer)
    out_of_sample_start: Mapped[date | None] = mapped_column(Date)
    universe_size: Mapped[int] = mapped_column(Integer)
    train_sample_count: Mapped[int] = mapped_column(Integer)
    hyperparameters_json: Mapped[str] = mapped_column(Text)
    seed: Mapped[int] = mapped_column(Integer)
    artifact: Mapped[str] = mapped_column(Text)
    input_bar_version_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class ModelEvaluationRow(Base):
    __tablename__: str = "model_evaluation"
    __table_args__: tuple[UniqueConstraint, CheckConstraint, dict[str, str]] = (
        UniqueConstraint(
            "model_id",
            "fold_index",
            "metric_name",
            name="uq_model_evaluation_metric",
        ),
        CheckConstraint("fold_index >= 1", name="ck_model_evaluation_fold_index"),
        {"schema": "ml"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    model_id: Mapped[UUID] = mapped_column(ForeignKey("ml.model.id", ondelete="CASCADE"))
    fold_index: Mapped[int] = mapped_column(Integer)
    valid_start: Mapped[date] = mapped_column(Date)
    valid_end: Mapped[date] = mapped_column(Date)
    sample_count: Mapped[int] = mapped_column(Integer)
    metric_name: Mapped[str] = mapped_column(String(32))
    metric_value: Mapped[Decimal] = mapped_column(Numeric(18, 6))


@final
class FeatureImportanceRow(Base):
    __tablename__: str = "feature_importance"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("model_id", "feature_name", name="uq_feature_importance_name"),
        {"schema": "ml"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    model_id: Mapped[UUID] = mapped_column(ForeignKey("ml.model.id", ondelete="CASCADE"))
    feature_name: Mapped[str] = mapped_column(String(40))
    importance: Mapped[Decimal] = mapped_column(Numeric(18, 8))
