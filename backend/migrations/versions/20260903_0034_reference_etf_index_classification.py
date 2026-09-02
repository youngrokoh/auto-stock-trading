"""ETF 추종 지수를 버전 사실로 둔다(ADR-0021 결정 3).

`market.etf_nav`는 덮어써지는 최신 스냅샷이다. 위험 판정의 입력이 그 행이면 나중에 "왜 그 주문이
통과했는가"를 재구성할 수 없다. 같은 값 재관측은 증거만 갱신하고, 값이 바뀌면 새 버전이다.

Revision ID: 20260903_0034
Revises: 20260901_0033
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0034"
down_revision: str | None = "20260901_0033"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "etf_index_classification",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("index_name", sa.String(120), nullable=False),
        sa.Column("tracking_multiple", sa.Numeric(8, 2), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
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
            "symbol",
            "source",
            "version",
            name="uq_etf_index_classification_version",
        ),
        sa.CheckConstraint("version >= 1", name="ck_etf_index_classification_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at > valid_from",
            name="ck_etf_index_classification_validity",
        ),
        schema="reference",
    )
    op.create_index(
        "uq_etf_index_classification_current",
        "etf_index_classification",
        ["symbol", "source"],
        unique=True,
        schema="reference",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_etf_index_classification_current",
        table_name="etf_index_classification",
        schema="reference",
    )
    op.drop_table("etf_index_classification", schema="reference")
