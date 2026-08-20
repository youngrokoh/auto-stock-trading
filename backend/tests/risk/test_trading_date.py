from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from auto_stock_trading.domain.risk.limits import seoul_trading_date

_SEOUL: Final = ZoneInfo("Asia/Seoul")


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # 서울 08:43은 UTC로 전날 23:43이다. UTC 날짜를 쓰면 거래일이 하루 밀린다.
        (datetime(2026, 8, 19, 23, 43, tzinfo=UTC), date(2026, 8, 20)),
        (datetime(2026, 8, 19, 15, 0, tzinfo=UTC), date(2026, 8, 20)),
        (datetime(2026, 8, 20, 0, 5, tzinfo=UTC), date(2026, 8, 20)),
        (datetime(2026, 8, 20, 6, 30, tzinfo=UTC), date(2026, 8, 20)),
        (datetime(2026, 8, 20, 14, 59, tzinfo=UTC), date(2026, 8, 20)),
    ],
)
def test_the_trading_date_follows_the_exchange_timezone(
    moment: datetime,
    expected: date,
) -> None:
    assert seoul_trading_date(moment) == expected


def test_the_trading_date_is_stable_across_the_whole_seoul_day() -> None:
    start = datetime(2026, 8, 20, 0, 0, tzinfo=_SEOUL)
    dates = {
        seoul_trading_date(start + timedelta(minutes=minute)) for minute in range(0, 24 * 60, 30)
    }

    assert dates == {date(2026, 8, 20)}


def test_a_moment_before_midnight_in_seoul_is_the_earlier_trading_date() -> None:
    just_before_midnight = datetime(2026, 8, 20, 23, 59, tzinfo=_SEOUL)

    assert seoul_trading_date(just_before_midnight) == date(2026, 8, 20)
    assert seoul_trading_date(just_before_midnight + timedelta(minutes=2)) == date(2026, 8, 21)
