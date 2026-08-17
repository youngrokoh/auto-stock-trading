import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0011"
down_revision: str | None = "20260817_0010"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "investor_flow",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("individual_net_quantity", sa.BigInteger(), nullable=False),
        sa.Column("foreign_net_quantity", sa.BigInteger(), nullable=False),
        sa.Column("institution_net_quantity", sa.BigInteger(), nullable=False),
        sa.Column("individual_net_value", sa.BigInteger(), nullable=False),
        sa.Column("foreign_net_value", sa.BigInteger(), nullable=False),
        sa.Column("institution_net_value", sa.BigInteger(), nullable=False),
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
        sa.UniqueConstraint(
            "instrument_id",
            "trading_date",
            "source",
            "version",
            name="uq_investor_flow_version",
        ),
        sa.CheckConstraint("version >= 1", name="ck_investor_flow_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at > valid_from",
            name="ck_investor_flow_validity",
        ),
        schema="market",
    )
    op.create_index(
        "uq_investor_flow_current",
        "investor_flow",
        ["instrument_id", "trading_date", "source"],
        unique=True,
        schema="market",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_investor_flow_instrument_trading_date",
        "investor_flow",
        ["instrument_id", "trading_date"],
        schema="market",
    )

    _ = op.create_table(
        "disclosure",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("corp_code", sa.String(8), nullable=False),
        sa.Column("rcept_no", sa.String(14), nullable=False),
        sa.Column("report_nm", sa.String(300), nullable=False),
        sa.Column("flr_nm", sa.String(120), nullable=False),
        sa.Column("rcept_dt", sa.Date(), nullable=False),
        sa.Column("disclosure_type", sa.String(1), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "raw_response_id",
            sa.Uuid(),
            sa.ForeignKey("operations.raw_api_response.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("instrument_id", "rcept_no", name="uq_disclosure_receipt"),
        sa.CheckConstraint(
            "disclosure_type IN ('A', 'B', 'D', 'I')",
            name="ck_disclosure_type",
        ),
        schema="fundamental",
    )
    op.create_index(
        "ix_disclosure_instrument_rcept_dt",
        "disclosure",
        ["instrument_id", "rcept_dt"],
        schema="fundamental",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_disclosure_instrument_rcept_dt", table_name="disclosure", schema="fundamental"
    )
    op.drop_table("disclosure", schema="fundamental")
    op.drop_index(
        "ix_investor_flow_instrument_trading_date",
        table_name="investor_flow",
        schema="market",
    )
    op.drop_index("uq_investor_flow_current", table_name="investor_flow", schema="market")
    op.drop_table("investor_flow", schema="market")
