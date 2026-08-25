"""실전 전환 게이트 판정(모의투자·실전투자 전환 게이트 §3·§4·§6).

이 판정의 핵심은 **판정 불가와 미충족을 구분**하는 것이다. 사람이 확인해야 하는 조건을 기계가
'통과'로 보이게 하면 게이트가 무의미해진다.
"""

from datetime import UTC, datetime
from typing import Final

from auto_stock_trading.domain.gate.readiness import (
    GateConditionState,
    GateMeasurements,
    GateReadiness,
    GateSection,
    evaluate_gate,
    initial_live_limits,
)

_NOW: Final = datetime(2026, 8, 25, 6, 0, tzinfo=UTC)


def _measurements(**overrides: int) -> GateMeasurements:
    base: dict[str, int] = {
        "paper_trading_days": 3,
        "rebalance_cycles": 1,
        "filled_orders": 8,
        "duplicate_orders": 0,
        "unreconciled_events": 2,
        "severe_incidents_20d": 1,
        "stale_open_orders": 0,
    }
    base.update(overrides)
    return GateMeasurements(
        paper_trading_days=base["paper_trading_days"],
        rebalance_cycles=base["rebalance_cycles"],
        filled_orders=base["filled_orders"],
        duplicate_orders=base["duplicate_orders"],
        unreconciled_events=base["unreconciled_events"],
        severe_incidents_20d=base["severe_incidents_20d"],
        stale_open_orders=base["stale_open_orders"],
    )


def test_every_condition_carries_a_code_and_a_section() -> None:
    result = evaluate_gate(_measurements(), _NOW)

    assert result.conditions
    assert all(condition.code for condition in result.conditions)
    assert {condition.section for condition in result.conditions} == set(GateSection)


def test_a_count_below_the_threshold_is_not_met() -> None:
    result = evaluate_gate(_measurements(paper_trading_days=3), _NOW)

    days = next(item for item in result.conditions if item.code == "PAPER_TRADING_DAYS")
    assert days.state is GateConditionState.NOT_MET
    assert days.measured == "3"
    assert days.threshold == "60"


def test_a_count_at_the_threshold_is_met() -> None:
    result = evaluate_gate(_measurements(paper_trading_days=60), _NOW)

    days = next(item for item in result.conditions if item.code == "PAPER_TRADING_DAYS")
    assert days.state is GateConditionState.MET


def test_a_zero_ceiling_condition_is_met_only_at_zero() -> None:
    """미조정 0건 같은 조건은 '이하'가 아니라 '0'이다."""
    blocked = evaluate_gate(_measurements(unreconciled_events=1), _NOW)
    clean = evaluate_gate(_measurements(unreconciled_events=0), _NOW)

    assert _state(blocked, "UNRECONCILED_ITEMS") is GateConditionState.NOT_MET
    assert _state(clean, "UNRECONCILED_ITEMS") is GateConditionState.MET


def test_conditions_without_a_source_are_not_measurable() -> None:
    """가용성·시나리오·슬리피지 보고서는 저장된 사실로 판정할 수 없다.

    '미충족'으로 두면 데이터가 생기면 자동으로 통과할 것처럼 보이고, '충족'으로 두면 거짓이다.
    """
    result = evaluate_gate(_measurements(), _NOW)

    for code in ("AVAILABILITY", "FAILURE_SCENARIOS", "SLIPPAGE_REPORT"):
        condition = next(item for item in result.conditions if item.code == code)
        assert condition.state is GateConditionState.NOT_MEASURABLE
        assert condition.reason_code is not None
        assert condition.measured is None


def test_the_gate_is_not_passed_while_anything_is_unmet_or_unmeasurable() -> None:
    result = evaluate_gate(
        _measurements(
            paper_trading_days=60,
            rebalance_cycles=10,
            filled_orders=20,
            unreconciled_events=0,
            severe_incidents_20d=0,
        ),
        _NOW,
    )

    # 기계 판정은 전부 충족이지만 사람이 확인할 항목이 남아 있다.
    assert all(
        item.state is GateConditionState.MET
        for item in result.conditions
        if item.state is not GateConditionState.NOT_MEASURABLE
    )
    assert result.passed is False
    assert result.blocking_codes


def test_blocking_codes_list_what_actually_blocks() -> None:
    result = evaluate_gate(_measurements(), _NOW)

    assert "PAPER_TRADING_DAYS" in result.blocking_codes
    assert "AVAILABILITY" in result.blocking_codes


def test_initial_live_limits_are_the_policy_numbers() -> None:
    """§6의 최초 실전 한도. 화면이 값을 만들지 않고 정책을 그대로 보여준다."""
    limits = initial_live_limits()

    codes = {item.code for item in limits}
    assert "LIVE_TOTAL_EXPOSURE" in codes
    assert "LIVE_DAILY_ATTEMPTS" in codes
    total = next(item for item in limits if item.code == "LIVE_TOTAL_EXPOSURE")
    assert total.value == "20%"


def _state(result: GateReadiness, code: str) -> GateConditionState:
    return next(item.state for item in result.conditions if item.code == code)


def test_a_stale_open_order_blocks_the_reconciliation_condition() -> None:
    """거래일이 지난 미종결 주문도 미조정이다(ADR-0017 결정 6).

    문제 이벤트만 세면 세션 종료 잔재가 남아 있는데도 '미조정 0건'이 거짓으로 통과한다.
    """
    result = evaluate_gate(
        _measurements(unreconciled_events=0, stale_open_orders=1),
        _NOW,
    )

    assert _state(result, "UNRECONCILED_ITEMS") is GateConditionState.NOT_MET
    assert "UNRECONCILED_ITEMS" in result.blocking_codes


def test_no_events_and_no_stale_orders_meets_the_condition() -> None:
    result = evaluate_gate(
        _measurements(unreconciled_events=0, stale_open_orders=0),
        _NOW,
    )

    assert _state(result, "UNRECONCILED_ITEMS") is GateConditionState.MET
