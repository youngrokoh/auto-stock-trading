"""거래일 변경 시 자동매매 복귀 규칙(거래 안전 정책 §6). 순수 함수다.

정책은 "서버 재시작, 거래일 변경 또는 자격증명 환경 변경 시 상태는 **항상** `DISABLED`로
돌아간다"고 정한다. '항상'이므로 규칙이 한 경로에만 있으면 안 된다 — 계획은 리셋하는데 제출
게이트와 조회가 저장된 값을 그대로 믿으면, 어제 켠 상태가 오늘 살아 있는 것처럼 보인다.
"""

from datetime import UTC, date, datetime

from auto_stock_trading.domain.orders.models import AutomationState
from auto_stock_trading.domain.orders.records import AutomationRecord
from auto_stock_trading.domain.orders.recovery import (
    STALE_TRADING_DAY_REASON,
    effective_automation_state,
    is_stale_trading_day,
)

_TODAY = date(2026, 8, 24)
_YESTERDAY = date(2026, 8, 21)
_NOW = datetime(2026, 8, 24, 0, 30, tzinfo=UTC)


def _record(state: AutomationState, trading_date: date | None) -> AutomationRecord:
    return AutomationRecord(
        environment="paper",
        state=state,
        reason_code=None,
        trading_date=trading_date,
        changed_at=_NOW,
    )


def test_a_record_from_a_previous_trading_day_is_stale() -> None:
    assert is_stale_trading_day(_record(AutomationState.RUNNING, _YESTERDAY), _TODAY) is True


def test_todays_record_is_not_stale() -> None:
    assert is_stale_trading_day(_record(AutomationState.RUNNING, _TODAY), _TODAY) is False


def test_a_disabled_record_is_never_stale() -> None:
    """이미 DISABLED면 되돌릴 것이 없다. 사유를 덮어쓰지 않는다."""
    assert is_stale_trading_day(_record(AutomationState.DISABLED, _YESTERDAY), _TODAY) is False


def test_a_record_without_a_trading_date_is_not_stale() -> None:
    """거래일을 모르는 기록은 어제 것이라고 단정할 수 없다."""
    assert is_stale_trading_day(_record(AutomationState.ARMED, None), _TODAY) is False


def test_the_effective_state_of_a_stale_record_is_disabled() -> None:
    stale = _record(AutomationState.RUNNING, _YESTERDAY)

    assert effective_automation_state(stale, _TODAY) is AutomationState.DISABLED


def test_the_effective_state_of_a_current_record_is_the_stored_one() -> None:
    for state in (
        AutomationState.DISABLED,
        AutomationState.ARMED,
        AutomationState.RUNNING,
        AutomationState.PAUSED,
        AutomationState.EMERGENCY_STOP,
    ):
        assert effective_automation_state(_record(state, _TODAY), _TODAY) is state


def test_a_missing_record_is_disabled() -> None:
    assert effective_automation_state(None, _TODAY) is AutomationState.DISABLED


def test_every_non_disabled_state_goes_stale_across_a_trading_day() -> None:
    """EMERGENCY_STOP도 거래일이 바뀌면 되돌아간다 — 정책이 상태를 가리지 않는다."""
    for state in (
        AutomationState.ARMED,
        AutomationState.RUNNING,
        AutomationState.PAUSED,
        AutomationState.EMERGENCY_STOP,
    ):
        record = _record(state, _YESTERDAY)
        assert is_stale_trading_day(record, _TODAY) is True
        assert effective_automation_state(record, _TODAY) is AutomationState.DISABLED


def test_the_reason_code_is_shared_so_audit_rows_match() -> None:
    assert STALE_TRADING_DAY_REASON == "TRADING_DAY_CHANGED"
