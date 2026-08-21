"""ML 모델·평가·특징 중요도 저장(ML 신호 계약 §저장).

모델 산출물은 해당 모델의 안전한 네이티브 포맷 텍스트로만 저장한다. Python pickle은 임의 코드
실행 위험 때문에 쓰지 않는다(기술 스택 §6.1).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0025"
down_revision: str | None = "20260821_0024"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ml")
    _ = op.create_table(
        "model",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("algorithm", sa.String(24), nullable=False),
        sa.Column("feature_version", sa.String(24), nullable=False),
        sa.Column("target_definition", sa.String(80), nullable=False),
        sa.Column("train_start", sa.Date(), nullable=False),
        sa.Column("train_end", sa.Date(), nullable=False),
        sa.Column("embargo_days", sa.Integer(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False),
        sa.Column("train_sample_count", sa.Integer(), nullable=False),
        sa.Column("hyperparameters_json", sa.Text(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        # 네이티브 포맷 텍스트(Ridge 계수 JSON, LightGBM 모델 텍스트). pickle 금지.
        sa.Column("artifact", sa.Text(), nullable=False),
        sa.Column("input_bar_version_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("embargo_days >= horizon_days", name="ck_model_embargo_covers_horizon"),
        sa.CheckConstraint("train_sample_count > 0", name="ck_model_train_samples_positive"),
        sa.CheckConstraint("train_end >= train_start", name="ck_model_train_window"),
        sa.UniqueConstraint("name", "version", name="uq_model_name_version"),
        schema="ml",
    )
    op.create_index("ix_model_created_at", "model", ["created_at"], schema="ml")
    _ = op.create_table(
        "model_evaluation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("ml.model.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fold_index", sa.Integer(), nullable=False),
        sa.Column("valid_start", sa.Date(), nullable=False),
        sa.Column("valid_end", sa.Date(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(32), nullable=False),
        sa.Column("metric_value", sa.Numeric(18, 6), nullable=False),
        sa.UniqueConstraint(
            "model_id",
            "fold_index",
            "metric_name",
            name="uq_model_evaluation_metric",
        ),
        sa.CheckConstraint("fold_index >= 1", name="ck_model_evaluation_fold_index"),
        schema="ml",
    )
    _ = op.create_table(
        "feature_importance",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Uuid(),
            sa.ForeignKey("ml.model.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_name", sa.String(40), nullable=False),
        sa.Column("importance", sa.Numeric(18, 8), nullable=False),
        sa.UniqueConstraint("model_id", "feature_name", name="uq_feature_importance_name"),
        schema="ml",
    )


def downgrade() -> None:
    op.drop_table("feature_importance", schema="ml")
    op.drop_table("model_evaluation", schema="ml")
    op.drop_index("ix_model_created_at", table_name="model", schema="ml")
    op.drop_table("model", schema="ml")
    op.execute("DROP SCHEMA IF EXISTS ml CASCADE")
