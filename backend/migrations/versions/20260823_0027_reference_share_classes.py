"""상장 주식종류 사실. 보통주 하나에 우선주 목록이 딸린다(유니버스 계약 §주식종류 사실).

전략·주문 대상은 계속 보통주뿐이지만, 우선주를 모르면 시가총액과 주당 지표가 틀린다.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0027"
down_revision: str | None = "20260822_0026"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "share_class",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # 논리 키는 보통주 단축코드다. 회사 단위 사실을 보통주 코드로 식별한다.
        sa.Column("common_symbol", sa.String(9), nullable=False),
        sa.Column("symbol", sa.String(9), nullable=False),
        # 'common' 또는 'preferred'. 원천은 단축코드 6번째 자리로만 구분한다.
        sa.Column("class_kind", sa.String(16), nullable=False),
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
        sa.UniqueConstraint("symbol", "version", name="uq_share_class_version"),
        sa.CheckConstraint("version >= 1", name="ck_share_class_version"),
        sa.CheckConstraint(
            "class_kind IN ('common', 'preferred')",
            name="ck_share_class_kind",
        ),
        # 보통주 행은 자기 자신을 논리 키로 갖는다. 우선주는 짝지은 보통주를 갖는다.
        sa.CheckConstraint(
            "class_kind <> 'common' OR symbol = common_symbol",
            name="ck_share_class_common_identity",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at > valid_from",
            name="ck_share_class_validity",
        ),
        schema="reference",
    )
    op.create_index(
        "uq_share_class_current",
        "share_class",
        ["symbol"],
        unique=True,
        schema="reference",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_share_class_common_current",
        "share_class",
        ["common_symbol"],
        schema="reference",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_share_class_common_current",
        table_name="share_class",
        schema="reference",
    )
    op.drop_index("uq_share_class_current", table_name="share_class", schema="reference")
    op.drop_table("share_class", schema="reference")
