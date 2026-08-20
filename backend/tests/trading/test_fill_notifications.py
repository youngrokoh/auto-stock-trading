from decimal import Decimal
from typing import Final

import pytest

from auto_stock_trading.domain.orders.fills import OrderSnapshot, ReconcileProblem
from auto_stock_trading.domain.orders.models import OrderSide, OrderState
from auto_stock_trading.domain.orders.notifications import (
    NotificationFormatError,
    NotificationKind,
    apply_notification,
    mask_notification_payload,
    parse_notifications,
)

# 계약의 필드 순서대로 만든 통보 본문. 고객ID·계좌번호·계좌명 자리에는 검사용 표식을 넣는다.
_FIELDS: Final[tuple[str, ...]] = (
    "CUSTOMER-ID",  # 0 고객ID
    "1234567890",  # 1 계좌번호
    "0000012345",  # 2 주문번호
    "0000000000",  # 3 원주문번호
    "02",  # 4 매도매수구분(매수)
    "0",  # 5 정정구분
    "00",  # 6 주문종류
    "0",  # 7 주문조건
    "005930",  # 8 종목코드
    "2",  # 9 체결수량
    "250000",  # 10 체결단가
    "101530",  # 11 체결시각
    "0",  # 12 거부여부
    "2",  # 13 체결여부(체결)
    "2",  # 14 접수여부
    "91252",  # 15 지점번호
    "4",  # 16 주문수량
    "홍길동",  # 17 계좌명
    "삼성전자",  # 18 체결종목명
    "0",  # 19 신용구분
    "00000000",  # 20 신용대출일자
    "삼성전자",  # 21 체결종목명40
    "250000",  # 22 주문가격
)


def _payload(**overrides: str) -> str:
    fields: list[str] = list(_FIELDS)
    positions = {
        "broker_order_id": 2,
        "original_broker_order_id": 3,
        "side": 4,
        "revise_code": 5,
        "symbol": 8,
        "quantity": 9,
        "price": 10,
        "rejected": 12,
        "kind": 13,
        "accept_code": 14,
        "order_quantity": 16,
    }
    for name, value in overrides.items():
        fields[positions[name]] = value
    return "^".join(fields)


def _order(
    *,
    quantity: int = 4,
    filled_quantity: int = 0,
    average_fill_price: Decimal | None = None,
    state: OrderState = OrderState.SUBMITTED,
    symbol: str = "005930",
) -> OrderSnapshot:
    return OrderSnapshot(
        client_order_id="fixture-client-order-id",
        broker_order_id="0000012345",
        symbol=symbol,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=average_fill_price,
        state=state,
    )


def test_a_cancel_notification_reports_the_original_broker_order_id() -> None:
    """실측: 취소 요청은 자체 주문번호를 받고 원주문번호로 대상 주문을 가리킨다."""
    (notification,) = parse_notifications(
        _payload(
            broker_order_id="0000017468",
            original_broker_order_id="0000017323",
            kind="1",
            revise_code="2",
            accept_code="2",
            quantity="0",
            price="0",
        )
    )

    assert notification.broker_order_id == "0000017468"
    assert notification.original_broker_order_id == "0000017323"
    assert notification.matched_broker_order_id == "0000017323"


def test_a_plain_order_notification_matches_on_its_own_order_id() -> None:
    (notification,) = parse_notifications(_payload())

    assert notification.matched_broker_order_id == "0000012345"


def test_execution_notification_is_parsed_into_broker_facts() -> None:
    (notification,) = parse_notifications(_payload())

    assert notification.broker_order_id == "0000012345"
    assert notification.original_broker_order_id == "0000000000"
    assert notification.side is OrderSide.BUY
    assert notification.kind is NotificationKind.EXECUTION
    assert notification.quantity == 2
    assert notification.price == Decimal(250000)
    assert notification.order_quantity == 4
    assert notification.broker_event_time == "101530"
    assert notification.branch_no == "91252"
    assert not notification.rejected


def test_sell_side_and_order_notification_are_distinguished() -> None:
    (notification,) = parse_notifications(_payload(side="01", kind="1"))

    assert notification.side is OrderSide.SELL
    assert notification.kind is NotificationKind.ORDER


def test_two_records_in_one_frame_are_parsed_separately() -> None:
    payload = "^".join((_payload(), _payload(broker_order_id="0000067890")))

    notifications = parse_notifications(payload)

    assert [item.broker_order_id for item in notifications] == ["0000012345", "0000067890"]


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "005930^2",
        "^".join(_FIELDS[:-1]),
        "^".join((*_FIELDS, "extra")),
    ],
)
def test_field_count_violations_fail_closed(payload: str) -> None:
    with pytest.raises(NotificationFormatError):
        _ = parse_notifications(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"quantity": "two"},
        {"price": ""},
        {"side": "07"},
        {"kind": "9"},
        {"order_quantity": "-1"},
    ],
)
def test_unreadable_field_values_fail_closed(overrides: dict[str, str]) -> None:
    with pytest.raises(NotificationFormatError):
        _ = parse_notifications(_payload(**overrides))


def test_masking_removes_personal_fields_and_keeps_the_rest() -> None:
    masked = mask_notification_payload(_payload())

    fields = masked.split("^")
    assert fields[0] == "***"
    assert fields[1] == "***"
    assert fields[17] == "***"
    assert "CUSTOMER-ID" not in masked
    assert "1234567890" not in masked
    assert "홍길동" not in masked
    assert fields[2] == "0000012345"
    assert fields[8] == "005930"
    assert len(fields) == len(_FIELDS)


def test_masking_covers_every_record_of_a_multi_record_frame() -> None:
    masked = mask_notification_payload(f"{_payload()}^{_payload()}")

    assert "홍길동" not in masked
    assert masked.split("^").count("***") == 6


def test_partial_execution_accumulates_the_filled_quantity() -> None:
    (notification,) = parse_notifications(_payload())

    outcome = apply_notification(_order(), notification)

    assert outcome.state is OrderState.PARTIALLY_FILLED
    assert outcome.filled_quantity == 2
    assert outcome.average_fill_price == Decimal(250000)
    assert outcome.changed
    assert outcome.problem is None


def test_second_execution_completes_the_order_with_a_weighted_average_price() -> None:
    (notification,) = parse_notifications(_payload(quantity="2", price="240000"))

    outcome = apply_notification(
        _order(
            filled_quantity=2,
            average_fill_price=Decimal(250000),
            state=OrderState.PARTIALLY_FILLED,
        ),
        notification,
    )

    assert outcome.state is OrderState.FILLED
    assert outcome.filled_quantity == 4
    assert outcome.average_fill_price == Decimal(245000)


def test_rejection_notification_transitions_to_rejected() -> None:
    (notification,) = parse_notifications(_payload(rejected="1", kind="1", quantity="0"))

    outcome = apply_notification(_order(), notification)

    assert outcome.state is OrderState.REJECTED
    assert outcome.filled_quantity == 0
    assert outcome.changed


def test_order_notification_without_rejection_changes_nothing() -> None:
    (notification,) = parse_notifications(_payload(kind="1", quantity="4", accept_code="1"))

    outcome = apply_notification(_order(), notification)

    assert outcome.state is OrderState.SUBMITTED
    assert outcome.filled_quantity == 0
    assert not outcome.changed
    assert outcome.problem is None


def test_a_cancel_confirmation_cancels_the_order() -> None:
    """실측(2026-08-20): 취소 확인 통보는 `RCTF_CLS=2`·`ACPT_YN=2`로 오고 단가는 0이다."""
    (notification,) = parse_notifications(
        _payload(kind="1", revise_code="2", accept_code="2", quantity="0", price="0")
    )

    outcome = apply_notification(_order(), notification)

    assert outcome.state is OrderState.CANCELED
    assert outcome.filled_quantity == 0
    assert outcome.changed
    assert outcome.problem is None


def test_a_cancel_after_a_partial_fill_keeps_the_filled_quantity() -> None:
    (notification,) = parse_notifications(
        _payload(kind="1", revise_code="2", accept_code="2", quantity="0", price="0")
    )

    outcome = apply_notification(
        _order(
            quantity=4,
            filled_quantity=1,
            average_fill_price=Decimal(250000),
            state=OrderState.PARTIALLY_FILLED,
        ),
        notification,
    )

    assert outcome.state is OrderState.CANCELED
    assert outcome.filled_quantity == 1
    assert outcome.average_fill_price == Decimal(250000)


def test_a_revision_confirmation_does_not_transition() -> None:
    """정정 확인(`RCTF_CLS=1`)은 수량·가격 재계산 규칙이 없어 전이하지 않는다."""
    (notification,) = parse_notifications(
        _payload(kind="1", revise_code="1", accept_code="2", quantity="0", price="0")
    )

    outcome = apply_notification(_order(), notification)

    assert outcome.state is OrderState.SUBMITTED
    assert not outcome.changed


def test_an_order_acceptance_notification_does_not_cancel() -> None:
    (notification,) = parse_notifications(_payload(kind="1", accept_code="1", quantity="4"))

    outcome = apply_notification(_order(), notification)

    assert outcome.state is OrderState.SUBMITTED
    assert not outcome.changed


def test_symbol_mismatch_is_a_reconcile_problem() -> None:
    (notification,) = parse_notifications(_payload(symbol="069500"))

    outcome = apply_notification(_order(), notification)

    assert outcome.problem is ReconcileProblem.SYMBOL_MISMATCH
    assert not outcome.changed


def test_accumulation_beyond_the_order_quantity_is_a_reconcile_problem() -> None:
    (notification,) = parse_notifications(_payload(quantity="3"))

    outcome = apply_notification(_order(quantity=4, filled_quantity=2), notification)

    assert outcome.problem is ReconcileProblem.FILL_EXCEEDS_ORDER
    assert outcome.filled_quantity == 2
    assert not outcome.changed


def test_execution_on_a_terminal_order_is_a_reconcile_problem() -> None:
    (notification,) = parse_notifications(_payload(quantity="1"))

    outcome = apply_notification(
        _order(quantity=4, filled_quantity=4, state=OrderState.FILLED),
        notification,
    )

    assert outcome.problem is ReconcileProblem.TERMINAL_STATE_CHANGED
    assert not outcome.changed


def test_broker_order_quantity_mismatch_is_a_reconcile_problem() -> None:
    (notification,) = parse_notifications(_payload(order_quantity="10"))

    outcome = apply_notification(_order(quantity=4), notification)

    assert outcome.problem is ReconcileProblem.ORDER_QUANTITY_MISMATCH
    assert not outcome.changed
