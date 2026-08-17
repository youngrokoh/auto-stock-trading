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
    assert "CREATE TABLE reference.instrument" in migration_sql
    assert "CREATE TABLE operations.raw_api_response" in migration_sql
    assert "CREATE TABLE market.quote" in migration_sql
    assert "CREATE TABLE market.market_bar" in migration_sql
    assert "CONSTRAINT uq_market_bar_identity UNIQUE" in migration_sql
    assert "CONSTRAINT uq_market_bar_version UNIQUE" in migration_sql
    assert "CREATE UNIQUE INDEX uq_market_bar_current" in migration_sql
    assert "CONSTRAINT ck_market_bar_finality" in migration_sql
    assert "CONSTRAINT ck_market_bar_confirmation" in migration_sql
    assert "CONSTRAINT ck_market_bar_validity" in migration_sql
    assert "CREATE TABLE reference.market_calendar" in migration_sql
    assert "CONSTRAINT ck_market_calendar_session_window" in migration_sql
    assert "CREATE UNIQUE INDEX uq_market_calendar_current" in migration_sql
    assert "CREATE TABLE operations.scheduled_job_run" in migration_sql
    assert "CONSTRAINT uq_scheduled_job_execution UNIQUE" in migration_sql
    assert "CONSTRAINT ck_scheduled_job_state" in migration_sql
    assert "CREATE TABLE market.corporate_action" in migration_sql
    assert "CONSTRAINT uq_corporate_action_version UNIQUE" in migration_sql
    assert "CONSTRAINT uq_corporate_action_source_event UNIQUE" in migration_sql
    assert "CREATE UNIQUE INDEX uq_corporate_action_current" in migration_sql
    assert "CONSTRAINT ck_corporate_action_type" in migration_sql
    assert "CONSTRAINT ck_corporate_action_lifecycle" in migration_sql
    assert "CONSTRAINT ck_corporate_action_quality" in migration_sql
    assert "CONSTRAINT ck_corporate_action_time_precision" in migration_sql
    assert "CONSTRAINT ck_corporate_action_share_multiplier" in migration_sql
    assert "CONSTRAINT ck_corporate_action_amounts" in migration_sql
    assert "CONSTRAINT ck_corporate_action_version" in migration_sql
    assert "CONSTRAINT ck_corporate_action_validity" in migration_sql
