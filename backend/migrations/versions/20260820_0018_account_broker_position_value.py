"""계좌 대조용 증권사 평가합계. 보유 행 합계와 시세 시점이 달라 별도로 보관한다."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0018"
down_revision: str | None = "20260819_0017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # 이 컬럼 도입 전 스냅샷은 값을 모른다. 과거 행에 0을 채우지 않고 비워 둔다.
    op.add_column(
        "account_snapshot",
        sa.Column("broker_position_value", sa.Numeric(24, 0), nullable=True),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_column("account_snapshot", "broker_position_value", schema="trading")
