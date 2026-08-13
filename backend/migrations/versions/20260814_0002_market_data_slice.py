import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0002"
down_revision: str | None = "20260811_0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "instrument",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("exchange", sa.String(12), nullable=False),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("product_type", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("english_name", sa.String(240)),
        sa.Column("listed_on", sa.Date()),
        sa.Column("delisted_on", sa.Date()),
        sa.Column("trading_status", sa.String(24), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_as_of", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "country",
            "exchange",
            "symbol",
            "product_type",
            "currency",
            name="uq_instrument_identity",
        ),
        schema="reference",
    )
    op.create_index("ix_instrument_symbol", "instrument", ["symbol"], schema="reference")
    _ = op.create_table(
        "raw_api_response",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.String(240), nullable=False),
        sa.Column("request_fingerprint", sa.String(240), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="operations",
    )
    op.create_index(
        "ix_raw_api_response_operation",
        "raw_api_response",
        ["operation"],
        schema="operations",
    )
    op.create_index(
        "ix_raw_api_response_request_fingerprint",
        "raw_api_response",
        ["request_fingerprint"],
        schema="operations",
    )
    op.create_index(
        "ix_raw_api_response_received_at",
        "raw_api_response",
        ["received_at"],
        schema="operations",
    )
    _create_quote_table()
    _create_bar_table()
    _create_sync_table()


def _create_quote_table() -> None:
    _ = op.create_table(
        "quote",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("open_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("high_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("low_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("previous_close", sa.Numeric(24, 8), nullable=False),
        sa.Column("change", sa.Numeric(24, 8), nullable=False),
        sa.Column("change_percent", sa.Numeric(16, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("trading_value", sa.Numeric(32, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["reference.instrument.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_response_id"], ["operations.raw_api_response.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "source", name="uq_quote_latest_source"),
        schema="market",
    )
    op.create_index("ix_quote_instrument_id", "quote", ["instrument_id"], schema="market")


def _create_bar_table() -> None:
    _ = op.create_table(
        "market_bar",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("open_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("high_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("low_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("close_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("trading_value", sa.Numeric(32, 8), nullable=False),
        sa.Column("adjusted", sa.Boolean(), nullable=False),
        sa.Column("correction_code", sa.String(80)),
        sa.Column("split_ratio", sa.Numeric(24, 8)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_response_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["reference.instrument.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_response_id"], ["operations.raw_api_response.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id",
            "interval",
            "trading_date",
            "adjusted",
            "source",
            name="uq_market_bar_identity",
        ),
        schema="market",
    )
    op.create_index("ix_market_bar_instrument_id", "market_bar", ["instrument_id"], schema="market")
    op.create_index("ix_market_bar_trading_date", "market_bar", ["trading_date"], schema="market")


def _create_sync_table() -> None:
    _ = op.create_table(
        "api_sync_status",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(500)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "operation", "symbol", name="uq_sync_target"),
        schema="operations",
    )


def downgrade() -> None:
    op.drop_table("api_sync_status", schema="operations")
    op.drop_table("market_bar", schema="market")
    op.drop_table("quote", schema="market")
    op.drop_table("raw_api_response", schema="operations")
    op.drop_table("instrument", schema="reference")
