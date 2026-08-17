import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0009"
down_revision: str | None = "20260817_0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "financial_report",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("corp_code", sa.String(8), nullable=False),
        sa.Column("bsns_year", sa.Integer(), nullable=False),
        sa.Column("reprt_code", sa.String(5), nullable=False),
        sa.Column("fs_div", sa.String(3), nullable=False),
        sa.Column("rcept_no", sa.String(14), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
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
            "bsns_year",
            "reprt_code",
            "fs_div",
            "version",
            name="uq_financial_report_version",
        ),
        sa.UniqueConstraint(
            "instrument_id",
            "bsns_year",
            "reprt_code",
            "fs_div",
            "rcept_no",
            name="uq_financial_report_receipt",
        ),
        sa.CheckConstraint(
            "reprt_code IN ('11011', '11012', '11013', '11014')",
            name="ck_financial_report_reprt_code",
        ),
        sa.CheckConstraint("fs_div IN ('CFS', 'OFS')", name="ck_financial_report_fs_div"),
        sa.CheckConstraint("bsns_year >= 2000", name="ck_financial_report_year"),
        sa.CheckConstraint("version >= 1", name="ck_financial_report_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR (superseded_at > valid_from AND superseded_at > received_at)",
            name="ck_financial_report_validity",
        ),
        schema="fundamental",
    )
    op.create_index(
        "uq_financial_report_current",
        "financial_report",
        ["instrument_id", "bsns_year", "reprt_code", "fs_div"],
        unique=True,
        schema="fundamental",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    _ = op.create_table(
        "financial_statement_line",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "report_id",
            sa.Uuid(),
            sa.ForeignKey("fundamental.financial_report.id"),
            nullable=False,
        ),
        sa.Column("line_seq", sa.Integer(), nullable=False),
        sa.Column("sj_div", sa.String(3), nullable=False),
        sa.Column("account_id", sa.String(255)),
        sa.Column("account_nm", sa.String(200), nullable=False),
        sa.Column("account_detail", sa.String(200)),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("thstrm_nm", sa.String(40), nullable=False),
        sa.Column("thstrm_amount", sa.Numeric(32, 4)),
        sa.Column("frmtrm_nm", sa.String(40)),
        sa.Column("frmtrm_amount", sa.Numeric(32, 4)),
        sa.Column("bfefrmtrm_nm", sa.String(40)),
        sa.Column("bfefrmtrm_amount", sa.Numeric(32, 4)),
        sa.UniqueConstraint("report_id", "line_seq", name="uq_financial_statement_line_seq"),
        sa.CheckConstraint("line_seq >= 1", name="ck_financial_statement_line_seq"),
        sa.CheckConstraint(
            "sj_div IN ('BS', 'IS', 'CIS', 'CF', 'SCE')",
            name="ck_financial_statement_line_sj_div",
        ),
        schema="fundamental",
    )
    op.create_index(
        "ix_financial_statement_line_report",
        "financial_statement_line",
        ["report_id"],
        schema="fundamental",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_financial_statement_line_report",
        table_name="financial_statement_line",
        schema="fundamental",
    )
    op.drop_table("financial_statement_line", schema="fundamental")
    op.drop_index(
        "uq_financial_report_current", table_name="financial_report", schema="fundamental"
    )
    op.drop_table("financial_report", schema="fundamental")
