"""실전 전환 게이트 판정. 순수 함수다(모의투자·실전투자 전환 게이트 §3·§4·§6).

**판정 불가와 미충족을 구분한다.** 가용성·장애 시나리오·슬리피지 보고서는 저장된 사실로 판정할 수
없다. 미충족으로 두면 데이터가 쌓이면 자동으로 통과할 것처럼 보이고, 충족으로 두면 거짓이다. 그래서
세 번째 상태를 둔다 — 사람이 확인해야 한다는 사실 자체가 게이트의 내용이다.

한도(§6)는 정책 숫자를 그대로 옮긴다. 화면이 값을 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import datetime


class GateSection(StrEnum):
    """게이트 문서의 절. 화면이 절 단위로 묶어 보여준다."""

    BACKTEST = "backtest"
    PAPER_OPERATION = "paper_operation"


class GateConditionState(StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    # 저장된 사실로 판정할 수 없다. 통과도 미충족도 아니다.
    NOT_MEASURABLE = "not_measurable"


class GateReason(StrEnum):
    """판정 불가 사유. 무엇이 없어서 판정할 수 없는지 코드로 남긴다."""

    NO_UPTIME_SOURCE = "NO_UPTIME_SOURCE"
    HUMAN_REPORT_REQUIRED = "HUMAN_REPORT_REQUIRED"
    HUMAN_VERIFICATION_REQUIRED = "HUMAN_VERIFICATION_REQUIRED"
    NO_OUT_OF_SAMPLE_TAG = "NO_OUT_OF_SAMPLE_TAG"


@dataclass(frozen=True, slots=True)
class GateMeasurements:
    """저장된 사실에서 읽은 값. 없는 값을 여기에 넣지 않는다."""

    paper_trading_days: int
    rebalance_cycles: int
    filled_orders: int
    duplicate_orders: int
    unreconciled_events: int
    severe_incidents_20d: int


@dataclass(frozen=True, slots=True)
class GateCondition:
    code: str
    section: GateSection
    requirement: str
    threshold: str | None
    measured: str | None
    state: GateConditionState
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class GateLimit:
    code: str
    item: str
    value: str


@dataclass(frozen=True, slots=True)
class GateReadiness:
    evaluated_at: datetime
    conditions: tuple[GateCondition, ...]
    passed: bool
    blocking_codes: tuple[str, ...]


_MIN_TRADING_DAYS: Final = 60
_MIN_REBALANCE_CYCLES: Final = 10
_MIN_FILLED_ORDERS: Final = 20


def _at_least(code: str, requirement: str, measured: int, threshold: int) -> GateCondition:
    return GateCondition(
        code=code,
        section=GateSection.PAPER_OPERATION,
        requirement=requirement,
        threshold=str(threshold),
        measured=str(measured),
        state=GateConditionState.MET if measured >= threshold else GateConditionState.NOT_MET,
        reason_code=None,
    )


def _zero(code: str, requirement: str, measured: int) -> GateCondition:
    """'0건' 조건. 이하가 아니라 정확히 0일 때만 충족이다."""
    return GateCondition(
        code=code,
        section=GateSection.PAPER_OPERATION,
        requirement=requirement,
        threshold="0",
        measured=str(measured),
        state=GateConditionState.MET if measured == 0 else GateConditionState.NOT_MET,
        reason_code=None,
    )


def _unmeasurable(
    code: str,
    section: GateSection,
    requirement: str,
    reason: GateReason,
) -> GateCondition:
    return GateCondition(
        code=code,
        section=section,
        requirement=requirement,
        threshold=None,
        measured=None,
        state=GateConditionState.NOT_MEASURABLE,
        reason_code=reason.value,
    )


def evaluate_gate(measurements: GateMeasurements, evaluated_at: datetime) -> GateReadiness:
    """조건별 상태와 무엇이 막고 있는지를 돌려준다. 값을 만들지 않는다."""
    conditions = (
        _at_least(
            "PAPER_TRADING_DAYS",
            "60거래일 이상 운영",
            measurements.paper_trading_days,
            _MIN_TRADING_DAYS,
        ),
        _at_least(
            "REBALANCE_CYCLES",
            "예정 리밸런싱 주기 10회 이상 완료",
            measurements.rebalance_cycles,
            _MIN_REBALANCE_CYCLES,
        ),
        _at_least(
            "FILLED_ORDERS",
            "체결 주문 20건 이상 관찰",
            measurements.filled_orders,
            _MIN_FILLED_ORDERS,
        ),
        _zero("DUPLICATE_ORDERS", "중복 주문 0건", measurements.duplicate_orders),
        _zero(
            "UNRECONCILED_ITEMS",
            "내부와 증권사 상태의 미조정 0건",
            measurements.unreconciled_events,
        ),
        _zero(
            "SEVERE_INCIDENTS",
            "최근 20거래일 심각도 높은 장애 0건",
            measurements.severe_incidents_20d,
        ),
        _unmeasurable(
            "SLIPPAGE_REPORT",
            GateSection.PAPER_OPERATION,
            "계획 대비 체결 차이·슬리피지 보고서 확인",
            GateReason.HUMAN_REPORT_REQUIRED,
        ),
        _unmeasurable(
            "AVAILABILITY",
            GateSection.PAPER_OPERATION,
            "예정 실행시간 기준 가용성 99% 이상",
            GateReason.NO_UPTIME_SOURCE,
        ),
        _unmeasurable(
            "FAILURE_SCENARIOS",
            GateSection.PAPER_OPERATION,
            "비상정지·부분체결·거절·인증 만료·재시작·데이터 지연 시나리오 통과",
            GateReason.HUMAN_VERIFICATION_REQUIRED,
        ),
        _unmeasurable(
            "OUT_OF_SAMPLE",
            GateSection.BACKTEST,
            "표본 밖 성과 기준(샤프 0.7 이상, MDD 15% 이하 등)",
            GateReason.NO_OUT_OF_SAMPLE_TAG,
        ),
        _unmeasurable(
            "WALK_FORWARD",
            GateSection.BACKTEST,
            "워크포워드 검증 3개 구간 이상",
            GateReason.NO_OUT_OF_SAMPLE_TAG,
        ),
    )
    blocking = tuple(
        condition.code for condition in conditions if condition.state is not GateConditionState.MET
    )
    return GateReadiness(
        evaluated_at=evaluated_at,
        conditions=conditions,
        passed=not blocking,
        blocking_codes=blocking,
    )


def initial_live_limits() -> tuple[GateLimit, ...]:
    """§6 최초 실전 한도. 승인 시 이보다 완화할 수 없다."""
    return (
        GateLimit("LIVE_CAPITAL", "실전 자본", "지정 한도와 NAV 10% 중 작은 값"),
        GateLimit("LIVE_TOTAL_EXPOSURE", "총 투자 비중", "20%"),
        GateLimit("LIVE_SYMBOL_EXPOSURE", "종목별 비중", "2%"),
        GateLimit("LIVE_ORDER_SIZE", "주문 1건", "1%"),
        GateLimit("LIVE_DAILY_ATTEMPTS", "하루 주문 시도", "5건"),
        GateLimit("LIVE_DAILY_LOSS", "일일 손실", "-0.5%"),
        GateLimit("LIVE_CONCURRENT_STRATEGIES", "동시 실행 전략", "1개"),
    )
