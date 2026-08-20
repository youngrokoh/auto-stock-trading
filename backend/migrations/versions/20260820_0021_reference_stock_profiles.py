"""KOSPI200 구성종목 사실과 업종 키. ETF 마스터와 같은 버전 사실 패턴이다."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0021"
down_revision: str | None = "20260820_0020"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "stock_profile",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("isin", sa.String(12), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        # 업종 키는 KOSPI200 섹터업종 코드 1바이트다. 이름은 원천에 없다.
        sa.Column("sector_code", sa.String(2), nullable=False),
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
        sa.UniqueConstraint("symbol", "version", name="uq_stock_profile_version"),
        sa.CheckConstraint("version >= 1", name="ck_stock_profile_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at > valid_from",
            name="ck_stock_profile_validity",
        ),
        schema="reference",
    )
    op.create_index(
        "uq_stock_profile_current",
        "stock_profile",
        ["symbol"],
        unique=True,
        schema="reference",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_stock_profile_current", table_name="stock_profile", schema="reference")
    op.drop_table("stock_profile", schema="reference")
