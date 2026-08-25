"""외부 알림 선별과 메시지 조립. 순수 함수다(ADR-0014).

두 규칙을 여기에 모아 둔다. 전송 어댑터가 우회할 수 없어야 하기 때문이다.

1. **선별**: 사람이 행동할 수 있는 이벤트만 보낸다. 상태가 바뀌지 않은 주문 이벤트, 리스너
   부착·해제, 통과한 위험 판정은 제외한다.
2. **금지 필드**: 계좌 참조·NAV·현금·비율·자격증명은 어떤 경로로도 나가지 않는다. 사유 코드처럼
   자유 문자열인 필드에 그런 값이 흘러들 수 있으므로, 조립한 본문을 다시 검사해 걸린다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.orders.models import AutomationState, OrderSide

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

_SEOUL: Final = ZoneInfo("Asia/Seoul")

FORBIDDEN_FIELD_REASON: Final = "FORBIDDEN_FIELD"

# 계약 §공개 범위의 금지 목록. 자유 문자열(사유 코드·설명)에 섞여 들어오는 경우를 잡는다.
#
# **어휘가 아니라 값의 형태로 잡는다.** 처음에는 `account`·`nav` 같은 단어를 막았는데, 정당한 사유
# 코드 `ACCOUNT_NOT_RECONCILED`가 걸려 **중요한 경고가 조용히 사라졌다**(테스트가 잡았다). 위험한
# 것은 단어가 아니라 값이므로, `키=값` 형태와 계좌 해시 참조의 모양(12자 16진수)을 막는다.
_FORBIDDEN_PATTERNS: Final = (
    re.compile(r"\baccount\w*\s*[=:]", re.IGNORECASE),
    re.compile(r"\bnav\s*[=:]", re.IGNORECASE),
    re.compile(r"\b(token|chat_id|secret|api[_-]?key)\b", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{12}\b"),
    re.compile(r"계좌"),
    re.compile(r"현금"),
    re.compile(r"잔고"),
    re.compile(r"평가금액"),
)

_ORDER_EVENT: Final = "order_event"
_AUTOMATION_EVENT: Final = "automation_event"
_RISK_DECISION: Final = "risk_decision"

_NOTIFIABLE_AUTOMATION_TYPES: Final = frozenset(
    {
        "state_change",
        "reconcile_problem",
        "api_failure",
        "attestation",
        "schedule_blocked",
        # 해소를 보내지 않으면 푸시만 보는 사람은 문제가 계속 열려 있다고 읽는다(ADR-0018).
        "reconcile_resolved",
    }
)
# 예약 제출 차단은 경고다(ADR-0015 결정 6). `listener_state`는 사람이 있을 때 정상 흐름이라
# 제외하지만, 그 때문에 자동 제출이 멈춘 사실은 알려야 한다 — 주문이 없는 것과 구분되지 않으면
# 감시가 없다.
_WARNING_AUTOMATION_TYPES: Final = frozenset(
    {"reconcile_problem", "api_failure", "schedule_blocked"}
)
_WARNING_AUTOMATION_STATES: Final = frozenset(
    {AutomationState.PAUSED.value, AutomationState.EMERGENCY_STOP.value}
)
_BLOCKED: Final = "blocked"
# 상태가 바뀌지 않아도 알리는 주문 사유(ADR-0019 결정 2). **좁게 지정한다** — 요청 이벤트를 전부
# 알리면 사람이 방금 한 행동이 푸시로 되돌아오고 실제 소식이 그 사이에 묻힌다. 새 실패 코드가 생기면
# 하나씩 더한다.
_NOTIFIABLE_ORDER_REASONS: Final = frozenset({"cancel_failed"})


class EventSource(StrEnum):
    ORDER_EVENT = _ORDER_EVENT
    AUTOMATION_EVENT = _AUTOMATION_EVENT
    RISK_DECISION = _RISK_DECISION


class NotificationKind(StrEnum):
    ORDER_STATE = "order_state"
    AUTOMATION_STATE = "automation_state"
    RECONCILE_PROBLEM = "reconcile_problem"
    API_FAILURE = "api_failure"
    ATTESTATION = "attestation"
    RISK_BLOCK = "risk_block"
    SCHEDULE_BLOCKED = "schedule_blocked"
    RECONCILE_RESOLVED = "reconcile_resolved"


class NotificationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class NotificationCandidate:
    """알림 후보 한 건. 저장된 이벤트 행에서 그대로 읽은 값이다."""

    source: EventSource
    source_id: UUID
    occurred_at: datetime
    previous_state: str | None
    state: str | None
    reason_code: str | None
    symbol: str | None
    symbol_name: str | None
    side: OrderSide | None
    quantity: int | None
    limit_price: Decimal | None
    broker_order_id: str | None
    event_type: str | None
    rule_code: str | None


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    kind: NotificationKind
    severity: NotificationSeverity
    body: str
    # 금지 필드에 걸리면 본문 대신 사유가 남는다. 조용히 버리지 않는다.
    rejected_reason: str | None


def is_notifiable(candidate: NotificationCandidate) -> bool:
    """사람이 행동할 수 있는 이벤트인지 판정한다."""
    if candidate.source is EventSource.ORDER_EVENT:
        if candidate.reason_code in _NOTIFIABLE_ORDER_REASONS:
            return True
        return candidate.previous_state != candidate.state
    if candidate.source is EventSource.AUTOMATION_EVENT:
        return candidate.event_type in _NOTIFIABLE_AUTOMATION_TYPES
    return candidate.state == _BLOCKED


_AUTOMATION_KINDS: Final = {
    "reconcile_problem": NotificationKind.RECONCILE_PROBLEM,
    "api_failure": NotificationKind.API_FAILURE,
    "attestation": NotificationKind.ATTESTATION,
    "schedule_blocked": NotificationKind.SCHEDULE_BLOCKED,
    "reconcile_resolved": NotificationKind.RECONCILE_RESOLVED,
}


def _kind(candidate: NotificationCandidate) -> NotificationKind:
    if candidate.source is EventSource.ORDER_EVENT:
        return NotificationKind.ORDER_STATE
    if candidate.source is EventSource.RISK_DECISION:
        return NotificationKind.RISK_BLOCK
    return _AUTOMATION_KINDS.get(candidate.event_type or "", NotificationKind.AUTOMATION_STATE)


def _severity(candidate: NotificationCandidate, kind: NotificationKind) -> NotificationSeverity:
    if kind is NotificationKind.RISK_BLOCK:
        return NotificationSeverity.WARNING
    if candidate.reason_code in _NOTIFIABLE_ORDER_REASONS:
        # 노출을 줄이려 했는데 줄지 않았다. 상태 전이 알림과 같은 정보로 두면 묻힌다.
        return NotificationSeverity.WARNING
    if candidate.event_type in _WARNING_AUTOMATION_TYPES:
        return NotificationSeverity.WARNING
    if kind is NotificationKind.AUTOMATION_STATE and candidate.state in _WARNING_AUTOMATION_STATES:
        return NotificationSeverity.WARNING
    return NotificationSeverity.INFO


def _instrument(candidate: NotificationCandidate) -> str:
    if candidate.symbol is None:
        return ""
    name = candidate.symbol_name or ""
    return f"{candidate.symbol} {name}".strip()


def _order_terms(candidate: NotificationCandidate) -> str:
    parts: list[str] = []
    if candidate.side is not None:
        parts.append("매수" if candidate.side is OrderSide.BUY else "매도")
    if candidate.quantity is not None:
        parts.append(f"{candidate.quantity:,}주")
    if candidate.limit_price is not None:
        parts.append(f"{candidate.limit_price:,.0f}원")
    return " ".join(parts)


def _transition(candidate: NotificationCandidate) -> str:
    if candidate.previous_state is None:
        return candidate.state or ""
    return f"{candidate.previous_state} → {candidate.state}"


def _body(candidate: NotificationCandidate, kind: NotificationKind) -> str:
    at = candidate.occurred_at.astimezone(_SEOUL).strftime("%H:%M:%S")
    lines: list[str] = []
    if kind is NotificationKind.ORDER_STATE:
        lines.append(f"[주문] {_instrument(candidate)} {_order_terms(candidate)}".rstrip())
        lines.append(f"{_transition(candidate)} · {candidate.reason_code or '-'}")
    elif kind is NotificationKind.RISK_BLOCK:
        # 규칙 코드와 거절 사실만. 초과 금액·비율은 보내지 않는다(계약 §공개 범위).
        lines.append(f"[위험] 주문 거절 · {candidate.rule_code or '-'}")
        lines.append(f"{_instrument(candidate)} {_order_terms(candidate)}".strip())
    elif kind is NotificationKind.AUTOMATION_STATE:
        lines.append(f"[자동매매] {_transition(candidate)}")
        lines.append(f"사유 {candidate.reason_code or '-'}")
    else:
        lines.append(f"[{kind.value}] {candidate.reason_code or '-'}")
    if candidate.broker_order_id is not None:
        lines.append(f"증권사 주문 {candidate.broker_order_id}")
    lines.append(f"{at} KST")
    return "\n".join(line for line in lines if line)


def contains_forbidden_field(body: str) -> bool:
    """금지 필드가 본문에 섞였는지 본다. 값 형태(계좌 해시)까지 잡는다."""
    return any(pattern.search(body) for pattern in _FORBIDDEN_PATTERNS)


def build_message(candidate: NotificationCandidate) -> NotificationMessage:
    """보낼 본문을 만든다. 금지 필드가 섞였으면 본문 대신 사유를 남긴다."""
    kind = _kind(candidate)
    severity = _severity(candidate, kind)
    body = _body(candidate, kind)
    if contains_forbidden_field(body):
        return NotificationMessage(
            kind=kind,
            severity=severity,
            body="",
            rejected_reason=FORBIDDEN_FIELD_REASON,
        )
    return NotificationMessage(kind=kind, severity=severity, body=body, rejected_reason=None)
