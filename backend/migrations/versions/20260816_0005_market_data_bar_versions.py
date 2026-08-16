import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0005"
down_revision: str | None = "20260816_0004"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    confirmed = "(finality = 'confirmed' AND confirmed_at IS NOT NULL)"
    pending = "(finality = 'pending' AND confirmed_at IS NULL)"
    op.drop_constraint(
        "uq_market_bar_identity",
        "market_bar",
        schema="market",
        type_="unique",
    )
    op.add_column(
        "market_bar",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        schema="market",
    )
    op.add_column(
        "market_bar",
        sa.Column(
            "finality",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        schema="market",
    )
    op.add_column(
        "market_bar",
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        schema="market",
    )
    op.add_column(
        "market_bar",
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        schema="market",
    )
    op.add_column(
        "market_bar",
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        schema="market",
    )
    op.execute("UPDATE market.market_bar SET valid_from = received_at")
    op.alter_column("market_bar", "valid_from", nullable=False, schema="market")
    op.alter_column("market_bar", "version", server_default=None, schema="market")
    op.alter_column("market_bar", "finality", server_default=None, schema="market")
    op.create_check_constraint(
        "ck_market_bar_unadjusted",
        "market_bar",
        "adjusted IS FALSE",
        schema="market",
    )
    op.create_check_constraint(
        "ck_market_bar_finality",
        "market_bar",
        "finality IN ('pending', 'confirmed')",
        schema="market",
    )
    op.create_check_constraint(
        "ck_market_bar_confirmation",
        "market_bar",
        f"{confirmed} OR {pending}",
        schema="market",
    )
    op.create_check_constraint(
        "ck_market_bar_version",
        "market_bar",
        "version >= 1",
        schema="market",
    )
    op.create_check_constraint(
        "ck_market_bar_validity",
        "market_bar",
        "superseded_at IS NULL OR (superseded_at > valid_from AND superseded_at > received_at)",
        schema="market",
    )
    op.create_unique_constraint(
        "uq_market_bar_version",
        "market_bar",
        ["instrument_id", "interval", "trading_date", "source", "version"],
        schema="market",
    )
    op.create_index(
        "uq_market_bar_current",
        "market_bar",
        ["instrument_id", "interval", "trading_date", "source"],
        unique=True,
        schema="market",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_market_bar_current", table_name="market_bar", schema="market")
    op.drop_constraint(
        "uq_market_bar_version",
        "market_bar",
        schema="market",
        type_="unique",
    )
    for constraint_name in (
        "ck_market_bar_validity",
        "ck_market_bar_version",
        "ck_market_bar_confirmation",
        "ck_market_bar_finality",
        "ck_market_bar_unadjusted",
    ):
        op.drop_constraint(
            constraint_name,
            "market_bar",
            schema="market",
            type_="check",
        )
    for column_name in (
        "superseded_at",
        "valid_from",
        "confirmed_at",
        "finality",
        "version",
    ):
        op.drop_column("market_bar", column_name, schema="market")
    op.create_unique_constraint(
        "uq_market_bar_identity",
        "market_bar",
        ["instrument_id", "interval", "trading_date", "adjusted", "source"],
        schema="market",
    )
