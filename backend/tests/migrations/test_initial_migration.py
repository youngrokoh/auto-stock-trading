from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config

if TYPE_CHECKING:
    import pytest


def test_initial_migration_renders_reproducible_postgres_sql(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)

    migration_sql = capsys.readouterr().out
    assert "CREATE SCHEMA IF NOT EXISTS reference" in migration_sql
    assert "CREATE SCHEMA IF NOT EXISTS market" in migration_sql
    assert "CREATE SCHEMA IF NOT EXISTS operations" in migration_sql
