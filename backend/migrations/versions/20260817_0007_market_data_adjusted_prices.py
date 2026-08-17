import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0007"
down_revision: str | None = "20260816_0006"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "adjustment_dataset",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("method", sa.String(24), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=False),
        sa.Column("price_cutoff_date", sa.Date(), nullable=False),
        sa.Column("knowledge_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(40), nullable=False),
        sa.Column("input_bar_version_hash", sa.String(64), nullable=False),
        sa.Column("action_version_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(80)),
        schema="market",
    )
    op.create_check_constraint(
        "ck_adjustment_dataset_method",
        "adjustment_dataset",
        "method IN ('split_adjusted', 'total_return')",
        schema="market",
    )
    op.create_check_constraint(
        "ck_adjustment_dataset_status",
        "adjustment_dataset",
        "status IN ('building', 'published', 'superseded', 'failed')",
        schema="market",
    )
    op.create_check_constraint(
        "ck_adjustment_dataset_range",
        "adjustment_dataset",
        "range_start <= price_cutoff_date",
        schema="market",
    )
    op.create_index(
        "uq_adjustment_dataset_inputs",
        "adjustment_dataset",
        [
            "instrument_id",
            "interval",
            "method",
            "range_start",
            "price_cutoff_date",
            "knowledge_cutoff_at",
            "algorithm_version",
            "input_bar_version_hash",
            "action_version_hash",
        ],
        unique=True,
        schema="market",
        postgresql_where=sa.text("status IN ('building', 'published')"),
    )
    op.create_index(
        "ix_adjustment_dataset_lookup",
        "adjustment_dataset",
        ["instrument_id", "method", "price_cutoff_date"],
        schema="market",
    )
    _ = op.create_table(
        "adjustment_dataset_action",
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("market.adjustment_dataset.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "corporate_action_id",
            sa.Uuid(),
            sa.ForeignKey("market.corporate_action.id"),
            primary_key=True,
        ),
        sa.Column("action_key", sa.Uuid(), nullable=False),
        sa.Column("action_version", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_price_factor", sa.Numeric(32, 16), nullable=False),
        sa.Column("event_volume_factor", sa.Numeric(32, 16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="market",
    )
    op.create_check_constraint(
        "ck_adjustment_dataset_action_factors",
        "adjustment_dataset_action",
        "event_price_factor > 0 AND event_volume_factor > 0",
        schema="market",
    )
    op.create_index(
        "ix_adjustment_dataset_action_key",
        "adjustment_dataset_action",
        ["action_key"],
        schema="market",
    )
    _ = op.create_table(
        "adjusted_market_bar",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("market.adjustment_dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_bar_id",
            sa.Uuid(),
            sa.ForeignKey("market.market_bar.id"),
            nullable=False,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("open_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("high_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("low_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("close_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("trading_value", sa.Numeric(32, 8), nullable=False),
        sa.Column("price_factor", sa.Numeric(32, 16), nullable=False),
        sa.Column("volume_factor", sa.Numeric(32, 16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("dataset_id", "trading_date", name="uq_adjusted_market_bar_date"),
        schema="market",
    )
    op.create_check_constraint(
        "ck_adjusted_market_bar_factors",
        "adjusted_market_bar",
        "price_factor > 0 AND volume_factor > 0",
        schema="market",
    )


def downgrade() -> None:
    op.drop_table("adjusted_market_bar", schema="market")
    op.drop_table("adjustment_dataset_action", schema="market")
    op.drop_table("adjustment_dataset", schema="market")
