"""알림 선별과 메시지 조립(ADR-0014, 주문·위험 이벤트 외부 알림 계약).

계약의 핵심은 두 가지다. 사람이 행동할 수 있는 이벤트만 보내고, 금지 필드는 어떤 경로로도 나가지
않는다. 둘 다 순수 함수로 두어 전송 어댑터가 우회할 수 없게 한다.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from auto_stock_trading.domain.notifications.events import (
    FORBIDDEN_FIELD_REASON,
    EventSource,
    NotificationCandidate,
    NotificationKind,
    NotificationSeverity,
    build_message,
    is_notifiable,
)
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide, OrderState

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_AT: Final = datetime(2026, 8, 24, 5, 3, 11, tzinfo=UTC)
_ID: Final = UUID("00000000-0000-4000-8000-000000000701")


def _order_candidate(
    *,
    previous_state: OrderState | None = OrderState.SUBMITTED,
    state: OrderState = OrderState.FILLED,
) -> NotificationCandidate:
    return NotificationCandidate(
        source=EventSource.ORDER_EVENT,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=None if previous_state is None else previous_state.value,
        state=state.value,
        reason_code="FILL_NOTIFICATION",
        symbol="005930",
        symbol_name="삼성전자",
        side=OrderSide.BUY,
        quantity=2,
        limit_price=Decimal(250_000),
        broker_order_id="0000117057",
        event_type=None,
        rule_code=None,
    )


def test_an_order_state_change_is_notifiable() -> None:
    assert is_notifiable(_order_candidate()) is True


def test_an_order_event_without_a_state_change_is_not_notifiable() -> None:
    """부분 취소 요청·취소 실패처럼 상태가 그대로인 정보성 행은 보내지 않는다."""
    candidate = _order_candidate(previous_state=OrderState.SUBMITTED, state=OrderState.SUBMITTED)

    assert is_notifiable(candidate) is False


def test_a_listener_state_event_is_not_notifiable() -> None:
    """실제 기록 127건 중 30건이 listener_state다. 사람이 할 일이 없다."""
    candidate = NotificationCandidate(
        source=EventSource.AUTOMATION_EVENT,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=None,
        state=None,
        reason_code="LISTENER_ATTACHED",
        symbol=None,
        symbol_name=None,
        side=None,
        quantity=None,
        limit_price=None,
        broker_order_id=None,
        event_type="listener_state",
        rule_code=None,
    )

    assert is_notifiable(candidate) is False


@pytest.mark.parametrize(
    "event_type",
    ["state_change", "reconcile_problem", "api_failure", "attestation"],
)
def test_the_selected_automation_event_types_are_notifiable(event_type: str) -> None:
    candidate = NotificationCandidate(
        source=EventSource.AUTOMATION_EVENT,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=AutomationState.RUNNING.value,
        state=AutomationState.PAUSED.value,
        reason_code="RISK_DAILY_LOSS",
        symbol=None,
        symbol_name=None,
        side=None,
        quantity=None,
        limit_price=None,
        broker_order_id=None,
        event_type=event_type,
        rule_code=None,
    )

    assert is_notifiable(candidate) is True


def test_a_passed_risk_decision_is_not_notifiable() -> None:
    candidate = NotificationCandidate(
        source=EventSource.RISK_DECISION,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=None,
        state="passed",
        reason_code=None,
        symbol="005930",
        symbol_name="삼성전자",
        side=OrderSide.BUY,
        quantity=2,
        limit_price=Decimal(250_000),
        broker_order_id=None,
        event_type=None,
        rule_code="RISK_SYMBOL_EXPOSURE",
    )

    assert is_notifiable(candidate) is False


def test_a_blocked_risk_decision_is_a_warning_carrying_only_the_rule_code() -> None:
    """계약: 위험 알림은 위반 사실과 규칙 코드만 보낸다. 초과 금액·비율은 보내지 않는다."""
    candidate = NotificationCandidate(
        source=EventSource.RISK_DECISION,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=None,
        state="blocked",
        reason_code=None,
        symbol="005930",
        symbol_name="삼성전자",
        side=OrderSide.BUY,
        quantity=2,
        limit_price=Decimal(250_000),
        broker_order_id=None,
        event_type=None,
        rule_code="RISK_SYMBOL_EXPOSURE",
    )

    assert is_notifiable(candidate) is True
    message = build_message(candidate)
    assert message.kind is NotificationKind.RISK_BLOCK
    assert message.severity is NotificationSeverity.WARNING
    assert "RISK_SYMBOL_EXPOSURE" in message.body
    assert message.rejected_reason is None


def test_an_order_message_carries_the_symbol_quantity_price_and_reason() -> None:
    message = build_message(_order_candidate())

    assert message.kind is NotificationKind.ORDER_STATE
    assert message.severity is NotificationSeverity.INFO
    assert "삼성전자" in message.body
    assert "005930" in message.body
    assert "2" in message.body
    assert "250,000" in message.body
    assert "FILL_NOTIFICATION" in message.body
    assert "0000117057" in message.body
    # 시각은 서울 시간으로 읽힌다. UTC로 적으면 사람이 장 시간과 맞춰볼 수 없다.
    assert _AT.astimezone(_SEOUL).strftime("%H:%M") in message.body


def test_pausing_automation_is_a_warning() -> None:
    candidate = NotificationCandidate(
        source=EventSource.AUTOMATION_EVENT,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=AutomationState.RUNNING.value,
        state=AutomationState.PAUSED.value,
        reason_code="ACCOUNT_NOT_RECONCILED",
        symbol=None,
        symbol_name=None,
        side=None,
        quantity=None,
        limit_price=None,
        broker_order_id=None,
        event_type="state_change",
        rule_code=None,
    )

    message = build_message(candidate)

    assert message.kind is NotificationKind.AUTOMATION_STATE
    assert message.severity is NotificationSeverity.WARNING
    assert "ACCOUNT_NOT_RECONCILED" in message.body


def test_arming_automation_is_information() -> None:
    candidate = NotificationCandidate(
        source=EventSource.AUTOMATION_EVENT,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=AutomationState.DISABLED.value,
        state=AutomationState.ARMED.value,
        reason_code="USER_COMMAND",
        symbol=None,
        symbol_name=None,
        side=None,
        quantity=None,
        limit_price=None,
        broker_order_id=None,
        event_type="state_change",
        rule_code=None,
    )

    assert build_message(candidate).severity is NotificationSeverity.INFO


def test_a_body_carrying_an_account_reference_is_rejected_before_sending() -> None:
    """금지 필드는 코드로 막는다. 통과하지 못하면 전송하지 않고 사유를 남긴다."""
    candidate = NotificationCandidate(
        source=EventSource.AUTOMATION_EVENT,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=None,
        state=None,
        # 계좌 해시 참조가 사유 코드로 흘러든 경우. 실제로 일어날 수 있는 형태다.
        reason_code="account=4aec6939a6d3 NAV=10,000,000",
        symbol=None,
        symbol_name=None,
        side=None,
        quantity=None,
        limit_price=None,
        broker_order_id=None,
        event_type="api_failure",
        rule_code=None,
    )

    message = build_message(candidate)

    assert message.rejected_reason == FORBIDDEN_FIELD_REASON
    assert message.body == ""


def test_a_legitimate_reason_code_containing_account_is_not_blocked() -> None:
    """`ACCOUNT_NOT_RECONCILED`는 정당한 사유 코드다.

    어휘로 막으면 이 경고가 조용히 사라진다 — 위험한 것은 단어가 아니라 값이다. 이 테스트가
    그 회귀를 막는다.
    """
    candidate = NotificationCandidate(
        source=EventSource.AUTOMATION_EVENT,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=AutomationState.RUNNING.value,
        state=AutomationState.PAUSED.value,
        reason_code="ACCOUNT_NOT_RECONCILED",
        symbol=None,
        symbol_name=None,
        side=None,
        quantity=None,
        limit_price=None,
        broker_order_id=None,
        event_type="state_change",
        rule_code=None,
    )

    message = build_message(candidate)

    assert message.rejected_reason is None
    assert "ACCOUNT_NOT_RECONCILED" in message.body


def test_an_account_hash_reference_shape_is_blocked_even_without_a_label() -> None:
    """12자 16진수는 계좌 해시 참조의 모양이다. 이름 없이 값만 흘러들 수 있다."""
    candidate = NotificationCandidate(
        source=EventSource.AUTOMATION_EVENT,
        source_id=_ID,
        occurred_at=_AT,
        previous_state=None,
        state=None,
        reason_code="order_submit 4aec6939a6d3",
        symbol=None,
        symbol_name=None,
        side=None,
        quantity=None,
        limit_price=None,
        broker_order_id=None,
        event_type="api_failure",
        rule_code=None,
    )

    assert build_message(candidate).rejected_reason == FORBIDDEN_FIELD_REASON


def test_a_broker_order_id_is_not_mistaken_for_an_account_reference() -> None:
    """증권사 주문번호는 10자리다. 금지 형태(12자)와 겹치지 않아야 한다."""
    message = build_message(_order_candidate())

    assert message.rejected_reason is None
    assert "0000117057" in message.body
