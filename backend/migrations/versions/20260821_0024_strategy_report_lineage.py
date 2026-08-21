"""종합 순위 실행의 재무 보고서 계보(계약 v3).

일봉·기업행사 해시만으로는 재무 요인이 바뀌었을 때 결과 변화를 설명할 수 없다. 기존 실행에는
이 값이 없으므로 nullable이다.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0024"
down_revision: str | None = "20260820_0023"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "backtest_run",
        sa.Column("input_report_version_hash", sa.String(64), nullable=True),
        schema="strategy",
    )


def downgrade() -> None:
    op.drop_column("backtest_run", "input_report_version_hash", schema="strategy")
