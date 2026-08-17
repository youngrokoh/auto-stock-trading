import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0008"
down_revision: str | None = "20260817_0007"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    confirmed = "(finality = 'confirmed' AND confirmed_at IS NOT NULL)"
    pending = "(finality = 'pending' AND confirmed_at IS NULL)"
    price_floor = "low_price <= open_price AND low_price <= close_price AND low_price > 0"
    price_ceiling = "open_price <= high_price AND close_price <= high_price"
    _ = op.create_table(
        "minute_bar",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("bar_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("high_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("low_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("close_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("cumulative_trading_value", sa.Numeric(32, 8), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finality", sa.String(16), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column(
            "raw_response_id",
            sa.Uuid(),
            sa.ForeignKey("operations.raw_api_response.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "instrument_id",
            "interval",
            "bar_started_at",
            "source",
            "version",
            name="uq_minute_bar_version",
        ),
        sa.CheckConstraint(f"{price_floor} AND {price_ceiling}", name="ck_minute_bar_prices"),
        sa.CheckConstraint(
            "volume >= 0 AND cumulative_trading_value >= 0",
            name="ck_minute_bar_amounts",
        ),
        sa.CheckConstraint(
            "finality IN ('pending', 'confirmed')",
            name="ck_minute_bar_finality",
        ),
        sa.CheckConstraint(f"{confirmed} OR {pending}", name="ck_minute_bar_confirmation"),
        sa.CheckConstraint("version >= 1", name="ck_minute_bar_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR (superseded_at > valid_from AND superseded_at > received_at)",
            name="ck_minute_bar_validity",
        ),
        schema="market",
    )
    op.create_index(
        "uq_minute_bar_current",
        "minute_bar",
        ["instrument_id", "interval", "bar_started_at", "source"],
        unique=True,
        schema="market",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_minute_bar_instrument_trading_date",
        "minute_bar",
        ["instrument_id", "trading_date"],
        schema="market",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_minute_bar_instrument_trading_date",
        table_name="minute_bar",
        schema="market",
    )
    op.drop_index("uq_minute_bar_current", table_name="minute_bar", schema="market")
    op.drop_table("minute_bar", schema="market")
