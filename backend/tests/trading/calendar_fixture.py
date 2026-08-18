from datetime import UTC, date, datetime, time
from typing import Final
from uuid import uuid4
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarSource,
    ConfirmedVerification,
    MarketCalendarRecord,
    OpenMarketSession,
    SessionWindow,
)

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_RECEIVED_AT: Final = datetime(2026, 8, 19, 0, 0, tzinfo=UTC)


def trading_day_record(key: CalendarSessionKey) -> MarketCalendarRecord:
    """정규장이 열린 확정 거래일 한 건. 세션 창은 KRX 기본 시간이다."""
    trading_date = key.trading_date
    return MarketCalendarRecord(
        id=uuid4(),
        session=OpenMarketSession(
            key,
            SessionWindow(
                datetime.combine(trading_date, time(9, 0), _SEOUL),
                datetime.combine(trading_date, time(15, 30), _SEOUL),
            ),
        ),
        exchange_timezone="Asia/Seoul",
        source=CalendarSource("KRX", "https://example.test/calendar", date(2026, 1, 1)),
        received_at=_RECEIVED_AT,
        verification=ConfirmedVerification(_RECEIVED_AT),
        version=1,
        valid_from=_RECEIVED_AT,
        superseded_at=None,
        raw_response_id=uuid4(),
        created_at=_RECEIVED_AT,
        updated_at=_RECEIVED_AT,
    )
