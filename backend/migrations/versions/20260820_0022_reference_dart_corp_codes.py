"""DART 고유번호 매핑 사실. 배당 수집이 종목코드로 회사를 찾는 유일한 경로다."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0022"
down_revision: str | None = "20260820_0021"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "dart_corp_code",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("corp_code", sa.String(8), nullable=False),
        sa.Column("corp_name", sa.String(160), nullable=False),
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
        sa.UniqueConstraint("symbol", "version", name="uq_dart_corp_code_version"),
        sa.CheckConstraint("version >= 1", name="ck_dart_corp_code_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at > valid_from",
            name="ck_dart_corp_code_validity",
        ),
        schema="reference",
    )
    op.create_index(
        "uq_dart_corp_code_current",
        "dart_corp_code",
        ["symbol"],
        unique=True,
        schema="reference",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_dart_corp_code_current", table_name="dart_corp_code", schema="reference")
    op.drop_table("dart_corp_code", schema="reference")
