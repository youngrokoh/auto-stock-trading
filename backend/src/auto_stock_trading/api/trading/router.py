from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Final, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from auto_stock_trading.api.trading.models import (
    AccountPositionResponse,
    AccountSnapshotResponse,
    AccountSnapshotsResponse,
    AutomationEventResponse,
    AutomationResponse,
    OrderConditionsResponse,
    OrderListEntryResponse,
    OrderPlanResponse,
    OrderPlansResponse,
    OrderPlanSummaryResponse,
    OrderResponse,
    OrdersResponse,
    RiskDecisionResponse,
    RiskLimitsResponse,
    RiskLimitUsageResponse,
)
from auto_stock_trading.domain.orders.models import AutomationState
from auto_stock_trading.domain.risk.limits import PAPER_RISK_LIMITS
from auto_stock_trading.domain.risk.utilization import UsageState, limit_usage

if TYPE_CHECKING:
    from auto_stock_trading.domain.orders.records import (
        AutomationEventRecord,
        AutomationRecord,
        OrderListEntry,
        OrderPlanRecord,
        OrderPlanSummary,
        OrderRecord,
        StoredAccountSnapshot,
        TradingRiskState,
    )
    from auto_stock_trading.domain.risk.utilization import LimitUsage

_EVENT_LIMIT = 20

# 실전 한도는 전환 게이트를 통과한 뒤 별도로 정의한다. 여기서 완화하지 않는다.
_LIMITS: Final = PAPER_RISK_LIMITS


class TradingReader(Protocol):
    async def automation(self, environment: str) -> AutomationRecord | None: ...

    async def automation_events(
        self,
        environment: str,
        limit: int,
    ) -> tuple[AutomationEventRecord, ...]: ...

    async def account_snapshots(
        self,
        environment: str,
        limit: int,
    ) -> tuple[StoredAccountSnapshot, ...]: ...

    async def order_plans(self, environment: str, limit: int) -> tuple[OrderPlanSummary, ...]: ...

    async def order_plan(self, plan_id: UUID) -> OrderPlanRecord | None: ...

    async def orders(self, environment: str, limit: int) -> tuple[OrderListEntry, ...]: ...

    async def risk_state(
        self,
        environment: str,
        api_failure_window_seconds: int,
    ) -> TradingRiskState: ...

    async def close(self) -> None: ...


def _event_response(event: AutomationEventRecord) -> AutomationEventResponse:
    return AutomationEventResponse(
        event_type=event.event_type,
        previous_state=None if event.previous_state is None else event.previous_state.value,
        state=None if event.state is None else event.state.value,
        reason_code=event.reason_code,
        detail=event.detail,
        occurred_at=event.occurred_at,
    )


def _snapshot_response(stored: StoredAccountSnapshot) -> AccountSnapshotResponse:
    snapshot = stored.snapshot
    return AccountSnapshotResponse(
        snapshot_id=stored.snapshot_id,
        source=snapshot.source,
        environment=snapshot.environment,
        account_reference=snapshot.account_reference,
        currency=snapshot.currency,
        cash_balance=snapshot.cash_balance,
        orderable_cash=snapshot.orderable_cash,
        position_value=snapshot.position_value,
        nav=snapshot.nav,
        broker_net_asset=snapshot.broker_net_asset,
        trading_date=snapshot.trading_date,
        as_of=snapshot.as_of,
        received_at=snapshot.received_at,
        positions=tuple(
            AccountPositionResponse(
                symbol=position.symbol,
                quantity=position.quantity,
                orderable_quantity=position.orderable_quantity,
                average_price=position.average_price,
                current_price=position.current_price,
                evaluation_amount=position.evaluation_amount,
                profit_loss=position.profit_loss,
            )
            for position in snapshot.positions
        ),
    )


def _order_response(order: OrderRecord) -> OrderResponse:
    return OrderResponse(
        client_order_id=order.client_order_id,
        sequence=order.sequence,
        symbol=order.symbol,
        side=order.side.value,
        order_type=order.order_type.value,
        quantity=order.quantity,
        limit_price=order.limit_price,
        reference_price=order.reference_price,
        reference_source=order.reference_source,
        reference_received_at=order.reference_received_at,
        state=order.state.value,
        reject_code=order.reject_code,
        risk_decisions=tuple(
            RiskDecisionResponse(
                rule_code=decision.rule.value,
                limit_value=decision.limit_value,
                projected_value=decision.projected_value,
                passed=decision.passed,
            )
            for decision in order.decisions
        ),
    )


def _plan_response(plan: OrderPlanRecord) -> OrderPlanResponse:
    return OrderPlanResponse(
        plan_id=plan.plan_id,
        environment=plan.environment,
        strategy_name=plan.strategy_name,
        strategy_version=plan.strategy_version,
        parameters_json=plan.parameters_json,
        signal_date=plan.signal_date,
        trading_date=plan.trading_date,
        account_snapshot_id=plan.account_snapshot_id,
        nav_basis=plan.nav_basis,
        session_open_nav=plan.session_open_nav,
        automation_state=plan.automation_state.value,
        status=plan.status,
        block_code=plan.block_code,
        planned_at=plan.planned_at,
        orders=tuple(_order_response(order) for order in plan.orders),
    )


def _summary_response(summary: OrderPlanSummary) -> OrderPlanSummaryResponse:
    plan = summary.plan
    return OrderPlanSummaryResponse(
        plan_id=plan.plan_id,
        strategy_name=plan.strategy_name,
        strategy_version=plan.strategy_version,
        signal_date=plan.signal_date,
        trading_date=plan.trading_date,
        automation_state=plan.automation_state.value,
        status=plan.status,
        block_code=plan.block_code,
        planned_at=plan.planned_at,
        order_count=summary.order_count,
        rejected_count=summary.rejected_count,
    )


def _entry_response(entry: OrderListEntry) -> OrderListEntryResponse:
    return OrderListEntryResponse(
        client_order_id=entry.client_order_id,
        plan_id=entry.plan_id,
        trading_date=entry.trading_date,
        created_at=entry.created_at,
        sequence=entry.sequence,
        symbol=entry.symbol,
        side=entry.side.value,
        order_type=entry.order_type.value,
        quantity=entry.quantity,
        filled_quantity=entry.filled_quantity,
        limit_price=entry.limit_price,
        reference_price=entry.reference_price,
        reference_source=entry.reference_source,
        reference_received_at=entry.reference_received_at,
        state=entry.state.value,
        reject_code=entry.reject_code,
        broker_order_id=entry.broker_order_id,
        submitted_at=entry.submitted_at,
        average_fill_price=entry.average_fill_price,
    )


def _usage_state(state: TradingRiskState) -> UsageState:
    stored = state.snapshot
    snapshot = None if stored is None else stored.snapshot
    counters = state.counters
    positions = () if snapshot is None else snapshot.positions
    return UsageState(
        nav=None if snapshot is None else snapshot.nav,
        settled_cash=None if snapshot is None else snapshot.orderable_cash,
        position_value=None if snapshot is None else snapshot.position_value,
        max_position_value=(
            None
            if snapshot is None
            else max((position.evaluation_amount for position in positions), default=Decimal(0))
        ),
        session_open_nav=state.session_open_nav,
        peak_nav=state.peak_nav,
        max_order_amount=state.max_order_amount,
        daily_buy_amount=counters.daily_buy_amount,
        open_orders=counters.open_orders,
        daily_order_attempts=counters.daily_order_attempts,
        consecutive_rejects=counters.consecutive_rejects,
        api_failures=state.api_failures,
    )


def _usage_response(usage: LimitUsage) -> RiskLimitUsageResponse:
    return RiskLimitUsageResponse(
        rule_code=usage.rule.value,
        basis=usage.basis.value,
        comparison=usage.comparison.value,
        limit_value=usage.limit_value,
        current_value=usage.current_value,
        usage_ratio=usage.usage_ratio,
        reason=None if usage.reason is None else usage.reason.value,
    )


def _conditions_response() -> OrderConditionsResponse:
    return OrderConditionsResponse(
        order_window_start=_LIMITS.order_window_start,
        order_window_end=_LIMITS.order_window_end,
        quote_max_age_seconds=_LIMITS.quote_max_age_seconds,
        price_band=_LIMITS.price_band,
        api_failure_window_seconds=_LIMITS.api_failure_window_seconds,
    )


def _risk_limits_response(environment: str, state: TradingRiskState) -> RiskLimitsResponse:
    stored = state.snapshot
    snapshot = None if stored is None else stored.snapshot
    return RiskLimitsResponse(
        environment=environment,
        evaluated_at=state.evaluated_at,
        basis_date=state.basis_date,
        snapshot_id=None if stored is None else stored.snapshot_id,
        snapshot_as_of=None if snapshot is None else snapshot.as_of,
        nav_basis=None if snapshot is None else snapshot.nav,
        session_open_nav=state.session_open_nav,
        peak_nav=state.peak_nav,
        items=tuple(_usage_response(usage) for usage in limit_usage(_usage_state(state), _LIMITS)),
        conditions=_conditions_response(),
    )


def create_trading_router(trading: TradingReader, environment: str) -> APIRouter:
    router = APIRouter(prefix="/api/trading", tags=["trading"])

    async def automation() -> AutomationResponse:
        record = await trading.automation(environment)
        events = await trading.automation_events(environment, _EVENT_LIMIT)
        return AutomationResponse(
            environment=environment,
            state=AutomationState.DISABLED.value if record is None else record.state.value,
            reason_code=None if record is None else record.reason_code,
            trading_date=None if record is None else record.trading_date,
            changed_at=None if record is None else record.changed_at,
            events=tuple(_event_response(event) for event in events),
        )

    async def account_snapshots(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> AccountSnapshotsResponse:
        stored = await trading.account_snapshots(environment, limit)
        return AccountSnapshotsResponse(
            environment=environment,
            snapshots=tuple(_snapshot_response(item) for item in stored),
        )

    async def order_plans(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> OrderPlansResponse:
        summaries = await trading.order_plans(environment, limit)
        return OrderPlansResponse(
            environment=environment,
            plans=tuple(_summary_response(summary) for summary in summaries),
        )

    async def order_plan(plan_id: UUID) -> OrderPlanResponse:
        plan = await trading.order_plan(plan_id)
        if plan is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "order plan not found")
        return _plan_response(plan)

    async def orders(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> OrdersResponse:
        entries = await trading.orders(environment, limit)
        return OrdersResponse(
            environment=environment,
            orders=tuple(_entry_response(entry) for entry in entries),
        )

    async def risk_limits() -> RiskLimitsResponse:
        state = await trading.risk_state(environment, _LIMITS.api_failure_window_seconds)
        return _risk_limits_response(environment, state)

    router.add_api_route(
        "/automation",
        automation,
        methods=["GET"],
        description=(
            "자동매매 상태 머신의 현재 상태와 최근 이벤트를 반환한다. 상태 행이 없으면 정책 "
            "기본값인 disabled로 응답한다. 이벤트에는 상태 전이와 외부 API 실패가 함께 남는다."
        ),
    )
    router.add_api_route(
        "/account-snapshots",
        account_snapshots,
        methods=["GET"],
        description=(
            "저장된 계좌 스냅샷을 최신 순으로 반환한다. 계좌번호 원문은 저장·노출하지 않고 해시 "
            "참조만 포함한다. NAV는 우리 계산값이며 증권사 순자산금액을 대조용으로 함께 준다."
        ),
    )
    router.add_api_route(
        "/order-plans",
        order_plans,
        methods=["GET"],
        description=(
            "주문 계획 목록을 최신 순으로 반환한다. 차단된 계획도 사유 코드와 함께 포함되며 "
            "주문 수와 거절 수를 같이 준다."
        ),
    )
    router.add_api_route(
        "/order-plans/{plan_id}",
        order_plan,
        methods=["GET"],
        description=(
            "계획 하나의 상세와 주문·위험검사 판정 전체를 반환한다. 각 주문은 기준가 출처와 "
            "수신 시각, 적용된 모든 규칙의 한도값·예상값·통과 여부를 포함한다."
        ),
    )
    router.add_api_route(
        "/orders",
        orders,
        methods=["GET"],
        description=(
            "계획 경계를 넘어 주문을 최신 순으로 반환한다. 체결 수량은 저장된 값이며 주문 제출 "
            "단계가 없는 동안 계획·거절 주문은 항상 0이다. 값을 만들지 않는다."
        ),
    )
    router.add_api_route(
        "/risk-limits",
        risk_limits,
        methods=["GET"],
        description=(
            "거래 안전 정책 §3 한도 13종의 한도값과 현재 소진율, §4 주문 가능 조건을 반환한다. "
            "기준 스냅샷·장 시작 NAV·고점 NAV가 없으면 값 대신 사유 코드를 남긴다."
        ),
    )
    return router
