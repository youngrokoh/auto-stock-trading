from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.dialects.postgresql import Insert, insert

from auto_stock_trading.adapters.database.market_data_rows import SyncStatusRow
from auto_stock_trading.domain.market_data.models import SyncState

if TYPE_CHECKING:
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
