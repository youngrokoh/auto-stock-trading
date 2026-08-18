import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0012"
down_revision: str | None = "20260817_0011"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "etf_profile",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("isin", sa.String(12), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
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
        sa.UniqueConstraint("symbol", "version", name="uq_etf_profile_version"),
        sa.CheckConstraint("version >= 1", name="ck_etf_profile_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at > valid_from",
            name="ck_etf_profile_validity",
        ),
        schema="reference",
    )
    op.create_index(
        "uq_etf_profile_current",
        "etf_profile",
        ["symbol"],
        unique=True,
        schema="reference",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    _ = op.create_table(
        "etf_nav",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("change_percent", sa.Numeric(16, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("previous_volume", sa.BigInteger(), nullable=False),
        sa.Column("nav", sa.Numeric(24, 8), nullable=False),
        sa.Column("divergence_rate", sa.Numeric(16, 8), nullable=False),
        sa.Column("tracking_error", sa.Numeric(16, 8), nullable=False),
        sa.Column("tracking_multiple", sa.Numeric(8, 2), nullable=False),
        sa.Column("net_asset_total", sa.BigInteger(), nullable=False),
        sa.Column("listed_shares", sa.BigInteger(), nullable=False),
        sa.Column("manager", sa.String(80), nullable=False),
        sa.Column("index_name", sa.String(120), nullable=False),
        sa.Column("listing_date", sa.Date()),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "raw_response_id",
            sa.Uuid(),
            sa.ForeignKey("operations.raw_api_response.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("symbol", "source", name="uq_etf_nav_latest_source"),
        schema="market",
    )


def downgrade() -> None:
    op.drop_table("etf_nav", schema="market")
    op.drop_index("uq_etf_profile_current", table_name="etf_profile", schema="reference")
    op.drop_table("etf_profile", schema="reference")
