import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, override

if TYPE_CHECKING:
    from datetime import date

_CLIENT_ORDER_ID_LENGTH: Final = 32
_ORDER_SUBJECT: Final = "order"
_AUTOMATION_SUBJECT: Final = "automation"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT = "limit"


class OrderState(StrEnum):
    PLANNED = "planned"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELED = "canceled"
    # 세션 종료로 더 체결될 수 없음이 집계로 확인된 주문(ADR-0017). 우리가 취소한 것이 아니므로
    # canceled와 구분한다.
    EXPIRED = "expired"


class AutomationState(StrEnum):
    DISABLED = "disabled"
    ARMED = "armed"
    RUNNING = "running"
    PAUSED = "paused"
    EMERGENCY_STOP = "emergency_stop"


@dataclass(frozen=True, slots=True)
class InvalidTransitionError(Exception):
    subject: str
    current: str
    requested: str

    @override
    def __str__(self) -> str:
        return f"{self.subject}: {self.current} -> {self.requested} is not allowed"


# 거래 안전 정책 §6과 구현 로드맵 7단계의 주문 상태 그래프.
_ORDER_TRANSITIONS: Final[dict[OrderState, frozenset[OrderState]]] = {
    OrderState.PLANNED: frozenset({OrderState.SUBMITTED, OrderState.REJECTED, OrderState.CANCELED}),
    OrderState.SUBMITTED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELED,
            OrderState.EXPIRED,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELED,
            OrderState.EXPIRED,
        }
    ),
    OrderState.FILLED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.CANCELED: frozenset(),
    OrderState.EXPIRED: frozenset(),
}

# 거래 안전 정책 §6. 재시작·거래일 변경·자격증명 변경은 어떤 상태에서든 DISABLED 복귀다.
_AUTOMATION_TRANSITIONS: Final[dict[AutomationState, frozenset[AutomationState]]] = {
    AutomationState.DISABLED: frozenset({AutomationState.ARMED, AutomationState.EMERGENCY_STOP}),
    AutomationState.ARMED: frozenset(
        {
            AutomationState.RUNNING,
            AutomationState.PAUSED,
            AutomationState.DISABLED,
            AutomationState.EMERGENCY_STOP,
        }
    ),
    AutomationState.RUNNING: frozenset(
        {AutomationState.PAUSED, AutomationState.DISABLED, AutomationState.EMERGENCY_STOP}
    ),
    AutomationState.PAUSED: frozenset(
        {AutomationState.ARMED, AutomationState.DISABLED, AutomationState.EMERGENCY_STOP}
    ),
    AutomationState.EMERGENCY_STOP: frozenset({AutomationState.DISABLED}),
}


def next_order_state(current: OrderState, requested: OrderState) -> OrderState:
    if requested not in _ORDER_TRANSITIONS[current]:
        raise InvalidTransitionError(_ORDER_SUBJECT, current.value, requested.value)
    return requested


def next_automation_state(
    current: AutomationState,
    requested: AutomationState,
) -> AutomationState:
    if requested not in _AUTOMATION_TRANSITIONS[current]:
        raise InvalidTransitionError(_AUTOMATION_SUBJECT, current.value, requested.value)
    return requested


@dataclass(frozen=True, slots=True)
class OrderIdentity:
    strategy_name: str
    strategy_version: str
    signal_date: date
    symbol: str
    side: OrderSide
    sequence: int


def client_order_id(identity: OrderIdentity) -> str:
    material = "|".join(
        (
            identity.strategy_name,
            identity.strategy_version,
            identity.signal_date.isoformat(),
            identity.symbol,
            identity.side.value,
            str(identity.sequence),
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return digest[:_CLIENT_ORDER_ID_LENGTH]
