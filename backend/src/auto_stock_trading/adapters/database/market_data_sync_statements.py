from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import Insert, insert

from auto_stock_trading.adapters.database.market_data_rows import SyncStatusRow
from auto_stock_trading.domain.market_data.models import SyncState

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class SyncTarget:
    source: str
    operation: str
    symbol: str


def sync_started(target: SyncTarget, started_at: datetime) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=target.source,
        operation=target.operation,
        symbol=target.symbol,
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


def sync_succeeded(target: SyncTarget, completed_at: datetime) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=target.source,
        operation=target.operation,
        symbol=target.symbol,
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


def sync_failed(
    target: SyncTarget,
    failed_at: datetime,
    error_code: str,
    error_message: str,
) -> Insert:
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source=target.source,
        operation=target.operation,
        symbol=target.symbol,
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
