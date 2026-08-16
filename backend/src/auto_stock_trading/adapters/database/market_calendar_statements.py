from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import Insert, insert

from auto_stock_trading.adapters.database.market_data_rows import SyncStatusRow
from auto_stock_trading.domain.market_data.models import SyncState

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.market_data.calendar import CalendarObservation


def calendar_conflict_upsert(observation: CalendarObservation) -> Insert:
    received_at = observation.raw_response.received_at
    key = observation.session.key
    symbol = f"{key.exchange}:{key.trading_date}"
    error_code = "calendar_source_conflict"
    error_message = "Secondary source conflicts with the current KRX calendar fact"
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=observation.source.name,
        operation="market_calendar",
        symbol=symbol,
        state=SyncState.FAILED.value,
        started_at=received_at,
        completed_at=received_at,
        last_success_at=None,
        error_code=error_code,
        error_message=error_message,
    )
    return statement.on_conflict_do_update(
        constraint="uq_sync_target",
        set_={
            "state": SyncState.FAILED.value,
            "started_at": received_at,
            "completed_at": received_at,
            "error_code": error_code,
            "error_message": error_message,
        },
    )


def calendar_sync_started(source: str, target: str, started_at: datetime) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=source,
        operation="market_calendar",
        symbol=target,
        state=SyncState.RUNNING.value,
        started_at=started_at,
        completed_at=None,
        last_success_at=None,
        error_code=None,
        error_message=None,
    )
    return statement.on_conflict_do_update(
        constraint="uq_sync_target",
        set_={
            "state": SyncState.RUNNING.value,
            "started_at": started_at,
            "completed_at": None,
            "error_code": None,
            "error_message": None,
        },
    )


def calendar_sync_succeeded(source: str, target: str, completed_at: datetime) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=source,
        operation="market_calendar",
        symbol=target,
        state=SyncState.SUCCESS.value,
        started_at=completed_at,
        completed_at=completed_at,
        last_success_at=completed_at,
        error_code=None,
        error_message=None,
    )
    return statement.on_conflict_do_update(
        constraint="uq_sync_target",
        set_={
            "state": SyncState.SUCCESS.value,
            "completed_at": completed_at,
            "last_success_at": completed_at,
            "error_code": None,
            "error_message": None,
        },
    )


def calendar_sync_failed(
    source: str,
    target: str,
    failed_at: datetime,
    error_code: str,
    error_message: str,
) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=source,
        operation="market_calendar",
        symbol=target,
        state=SyncState.FAILED.value,
        started_at=failed_at,
        completed_at=failed_at,
        last_success_at=None,
        error_code=error_code,
        error_message=error_message,
    )
    return statement.on_conflict_do_update(
        constraint="uq_sync_target",
        set_={
            "state": SyncState.FAILED.value,
            "completed_at": failed_at,
            "error_code": error_code,
            "error_message": error_message,
        },
    )
