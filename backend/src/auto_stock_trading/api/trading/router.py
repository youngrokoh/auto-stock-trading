from typing import TYPE_CHECKING, Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from auto_stock_trading.api.trading.models import (
    AccountPositionResponse,
    AccountSnapshotResponse,
    AccountSnapshotsResponse,
    AutomationEventResponse,
    AutomationResponse,
    OrderPlanResponse,
    OrderPlansResponse,
    OrderPlanSummaryResponse,
    OrderResponse,
    RiskDecisionResponse,
)
from auto_stock_trading.domain.orders.models import AutomationState

if TYPE_CHECKING:
    from auto_stock_trading.domain.orders.records import (
        AutomationEventRecord,
        AutomationRecord,
        OrderPlanRecord,
        OrderPlanSummary,
        OrderRecord,
        StoredAccountSnapshot,
    )

_EVENT_LIMIT = 20


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
    return router
