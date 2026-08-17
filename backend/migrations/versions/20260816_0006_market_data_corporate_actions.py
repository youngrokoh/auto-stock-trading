import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0006"
down_revision: str | None = "20260816_0005"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_ACTION_TYPES = (
    "stock_split",
    "reverse_split",
    "stock_dividend",
    "cash_dividend",
    "etf_distribution",
    "rights_issue",
    "capital_reduction",
    "merger",
    "spin_off",
    "trading_suspension",
    "delisting",
)


def upgrade() -> None:
    dated = "(announced_at IS NULL AND time_precision = 'date')"
    timed = "(announced_at IS NOT NULL AND time_precision IN ('minute', 'second'))"
    cash = "(cash_amount IS NULL OR cash_amount >= 0)"
    subscription = "(subscription_price IS NULL OR subscription_price >= 0)"
    _ = op.create_table(
        "corporate_action",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("action_key", sa.Uuid(), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("lifecycle_status", sa.String(16), nullable=False),
        sa.Column("quality_state", sa.String(16), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True)),
        sa.Column("announcement_date", sa.Date(), nullable=False),
        sa.Column("time_precision", sa.String(8), nullable=False),
        sa.Column("ex_date", sa.Date()),
        sa.Column("effective_date", sa.Date()),
        sa.Column("record_date", sa.Date()),
        sa.Column("payment_date", sa.Date()),
        sa.Column("share_multiplier", sa.Numeric(24, 12)),
        sa.Column("cash_amount", sa.Numeric(24, 8)),
        sa.Column("currency", sa.String(3)),
        sa.Column("subscription_price", sa.Numeric(24, 8)),
        sa.Column(
            "related_instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id"),
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_event_id", sa.String(120), nullable=False),
        sa.Column("source_reference", sa.String(240), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column(
            "raw_response_id",
            sa.Uuid(),
            sa.ForeignKey("operations.raw_api_response.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="market",
    )
    op.create_check_constraint(
        "ck_corporate_action_type",
        "corporate_action",
        "action_type IN ({})".format(", ".join(f"'{name}'" for name in _ACTION_TYPES)),
        schema="market",
    )
    op.create_check_constraint(
        "ck_corporate_action_lifecycle",
        "corporate_action",
        "lifecycle_status IN ('announced', 'confirmed', 'cancelled')",
        schema="market",
    )
    op.create_check_constraint(
        "ck_corporate_action_quality",
        "corporate_action",
        "quality_state IN ('pending', 'verified', 'conflict', 'unsupported')",
        schema="market",
    )
    op.create_check_constraint(
        "ck_corporate_action_time_precision",
        "corporate_action",
        f"{dated} OR {timed}",
        schema="market",
    )
    op.create_check_constraint(
        "ck_corporate_action_share_multiplier",
        "corporate_action",
        "share_multiplier IS NULL OR share_multiplier > 0",
        schema="market",
    )
    op.create_check_constraint(
        "ck_corporate_action_amounts",
        "corporate_action",
        f"{cash} AND {subscription}",
        schema="market",
    )
    op.create_check_constraint(
        "ck_corporate_action_version",
        "corporate_action",
        "version >= 1",
        schema="market",
    )
    op.create_check_constraint(
        "ck_corporate_action_validity",
        "corporate_action",
        "superseded_at IS NULL OR (superseded_at > valid_from AND superseded_at > received_at)",
        schema="market",
    )
    op.create_unique_constraint(
        "uq_corporate_action_version",
        "corporate_action",
        ["action_key", "version"],
        schema="market",
    )
    op.create_unique_constraint(
        "uq_corporate_action_source_event",
        "corporate_action",
        ["source", "source_event_id", "version"],
        schema="market",
    )
    op.create_index(
        "uq_corporate_action_current",
        "corporate_action",
        ["action_key"],
        unique=True,
        schema="market",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_corporate_action_instrument_ex_date",
        "corporate_action",
        ["instrument_id", "ex_date"],
        schema="market",
    )
    op.create_index(
        "ix_corporate_action_instrument_effective_date",
        "corporate_action",
        ["instrument_id", "effective_date"],
        schema="market",
    )
    op.create_index(
        "ix_corporate_action_instrument_available_at",
        "corporate_action",
        ["instrument_id", "available_at"],
        schema="market",
    )


def downgrade() -> None:
    op.drop_table("corporate_action", schema="market")
