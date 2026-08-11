from alembic import op

revision: str = "20260811_0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

CREATE_SCHEMA_STATEMENTS = (
    "CREATE SCHEMA IF NOT EXISTS reference",
    "CREATE SCHEMA IF NOT EXISTS market",
    "CREATE SCHEMA IF NOT EXISTS fundamental",
    "CREATE SCHEMA IF NOT EXISTS strategy",
    "CREATE SCHEMA IF NOT EXISTS trading",
    "CREATE SCHEMA IF NOT EXISTS operations",
)

DROP_SCHEMA_STATEMENTS = (
    "DROP SCHEMA IF EXISTS operations CASCADE",
    "DROP SCHEMA IF EXISTS trading CASCADE",
    "DROP SCHEMA IF EXISTS strategy CASCADE",
    "DROP SCHEMA IF EXISTS fundamental CASCADE",
    "DROP SCHEMA IF EXISTS market CASCADE",
    "DROP SCHEMA IF EXISTS reference CASCADE",
)


def upgrade() -> None:
    for statement in CREATE_SCHEMA_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DROP_SCHEMA_STATEMENTS:
        op.execute(statement)
