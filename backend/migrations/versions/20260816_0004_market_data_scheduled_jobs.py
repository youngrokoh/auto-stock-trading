import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0004"
down_revision: str | None = "20260816_0003"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "scheduled_job_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(80), nullable=False),
        sa.Column("execution_key", sa.String(160), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("owner_token", sa.Uuid(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('running', 'succeeded', 'conflict', 'failed')",
            name="ck_scheduled_job_state",
        ),
        sa.CheckConstraint("attempt_count >= 1", name="ck_scheduled_job_attempt_count"),
        sa.CheckConstraint(
            "lease_expires_at > started_at",
            name="ck_scheduled_job_lease_window",
        ),
        sa.CheckConstraint(
            """
            (state = 'running' AND completed_at IS NULL) OR
            (state <> 'running' AND completed_at IS NOT NULL)
            """,
            name="ck_scheduled_job_completion",
        ),
        sa.CheckConstraint(
            """
            (state = 'failed' AND error_code IS NOT NULL) OR
            (state <> 'failed' AND error_code IS NULL)
            """,
            name="ck_scheduled_job_error",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_name",
            "execution_key",
            name="uq_scheduled_job_execution",
        ),
        schema="operations",
    )
    op.create_index(
        "ix_scheduled_job_state_lease",
        "scheduled_job_run",
        ["state", "lease_expires_at"],
        schema="operations",
    )


def downgrade() -> None:
    op.drop_table("scheduled_job_run", schema="operations")
