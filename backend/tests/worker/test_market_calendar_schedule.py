from datetime import UTC, datetime
from unittest.mock import patch

import anyio

from auto_stock_trading.settings.runtime import Environment, Settings
from auto_stock_trading.worker import market_calendar_schedule


def test_krx_schedule_uses_seoul_time_and_stable_schedule_ids() -> None:
    # Given / When
    schedules = market_calendar_schedule.krx_calendar_schedules(enabled=True)

    # Then
    assert schedules == [
        {
            "cron": "*/10 5 * * *",
            "cron_offset": "Asia/Seoul",
            "schedule_id": "krx-calendar-0500-0550-kst",
        },
        {
            "cron": "0,10,20 6 * * *",
            "cron_offset": "Asia/Seoul",
            "schedule_id": "krx-calendar-0600-0620-kst",
        },
        {
            "cron": "*/10 7-14 * * *",
            "cron_offset": "Asia/Seoul",
            "schedule_id": "krx-calendar-0700-1450-kst",
        },
    ]


def test_krx_keeps_retrying_after_the_early_window() -> None:
    """호스트가 새벽에 자고 있으면 이른 창은 통째로 비어 있다(2026-09-04 실측).

    KIS 확인은 KRX 성공을 전제하므로, 가장 좁은 창이 달력 사슬 전체의 단일 실패점이 된다. 확인
    쪽과 같은 시간대까지 재시도해야 기계가 깨어난 뒤 스스로 복구된다.
    """
    krx_hours = _scheduled_hours(market_calendar_schedule.krx_calendar_schedules(enabled=True))
    kis_hours = _scheduled_hours(market_calendar_schedule.kis_calendar_schedules(enabled=True))

    # 수집은 확인보다 먼저 시작하고, 확인이 도는 시간대를 덮는다.
    assert min(krx_hours) <= min(kis_hours)
    assert kis_hours - krx_hours == {15}


def _scheduled_hours(schedules: list[market_calendar_schedule.CronSchedule]) -> set[int]:
    hours: set[int] = set()
    for entry in schedules:
        field = entry["cron"].split()[1]
        if field.startswith("*/"):
            hours.update(range(24))
        elif "-" in field:
            start, end = (int(part) for part in field.split("-"))
            hours.update(range(start, end + 1))
        else:
            hours.update(int(part) for part in field.split(","))
    return hours


def test_kis_schedule_uses_the_approved_confirmation_window() -> None:
    # Given / When
    schedules = market_calendar_schedule.kis_calendar_schedules(enabled=True)

    # Then
    assert tuple(schedule["cron"] for schedule in schedules) == (
        "30,40,50 6 * * *",
        "*/10 7-14 * * *",
        "0,10,20 15 * * *",
    )
    assert {schedule["cron_offset"] for schedule in schedules} == {"Asia/Seoul"}


def test_calendar_schedules_are_disabled_by_default() -> None:
    # Given / When
    settings = Settings(environment=Environment.TEST)

    # Then
    assert settings.krx_calendar_schedule_enabled is False
    assert settings.kis_calendar_schedule_enabled is False
    assert market_calendar_schedule.krx_calendar_schedules(enabled=False) == []
    assert market_calendar_schedule.kis_calendar_schedules(enabled=False) == []


def test_december_krx_schedule_collects_current_and_next_year() -> None:
    # Given
    started_at = datetime(2026, 12, 1, 20, 0, tzinfo=UTC)

    # When
    years = market_calendar_schedule.krx_schedule_years(started_at)

    # Then
    assert years == (2026, 2027)


def test_scheduled_kis_confirmation_stays_disabled_in_paper_environment() -> None:
    # Given
    settings = Settings(environment=Environment.TEST)

    # When
    with patch(
        "auto_stock_trading.worker.market_calendar_schedule.Settings",
        return_value=settings,
    ):
        outcome = anyio.run(market_calendar_schedule.run_scheduled_kis_market_calendar_confirmation)

    # Then
    assert outcome == "disabled"
