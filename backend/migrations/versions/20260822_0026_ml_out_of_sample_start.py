"""모델의 표본 밖 시작일 저장(ADR-0012 결정 4).

학습 종료일 이후 엠바고가 끝나는 **거래일**은 학습 시점의 달력으로만 정확히 계산할 수 있다.
백테스트 창이 학습 창보다 뒤에 있으면 그 창의 달력만으로는 사이 거래일 수를 셀 수 없어 겹침
검사가 느슨해졌다(2026-08-22 실측). 계산한 날짜를 저장해 비교만 하게 한다.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0026"
down_revision: str | None = "20260822_0025"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "model",
        sa.Column("out_of_sample_start", sa.Date(), nullable=True),
        schema="ml",
    )
    op.create_check_constraint(
        "ck_model_out_of_sample_after_train",
        "model",
        "out_of_sample_start IS NULL OR out_of_sample_start > train_end",
        schema="ml",
    )


def downgrade() -> None:
    op.drop_constraint("ck_model_out_of_sample_after_train", "model", schema="ml")
    op.drop_column("model", "out_of_sample_start", schema="ml")
