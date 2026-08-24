from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast, final
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.api.trading.models import (
    AutomationResponse,
    NotificationStatusResponse,
)
from auto_stock_trading.domain.notifications.records import (
    NotificationEntryRecord,
    NotificationStatusRecord,
)
from auto_stock_trading.domain.orders.account import AccountPosition, AccountSnapshot
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    OrderSide,
    OrderState,
    OrderType,
)
from auto_stock_trading.domain.orders.records import (
    AutomationEventRecord,
    AutomationRecord,
    OrderListEntry,
    OrderPlanRecord,
    OrderPlanSummary,
    OrderRecord,
    StoredAccountSnapshot,
    StoredCounters,
    TradingRiskState,
)
from auto_stock_trading.domain.risk.engine import RiskDecision
from auto_stock_trading.domain.risk.limits import RiskRule
from auto_stock_trading.settings.runtime import Environment, Settings
from tests.api.automation_stub import NoAutomationReset

if TYPE_CHECKING:
    from auto_stock_trading.application.trading.planning import AutomationTransition

_NOW = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
_TRADING_DATE = date(2026, 8, 18)
_PLAN_ID = UUID("00000000-0000-4000-8000-000000000301")
_MISSING_PLAN_ID = UUID("00000000-0000-4000-8000-000000000999")
_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000302")


@final
class StubProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _plan() -> OrderPlanRecord:
    return OrderPlanRecord(
        plan_id=_PLAN_ID,
        environment="paper",
        strategy_name="ma-rsi",
        strategy_version="1",
        parameters_json='{"short_period":5}',
        signal_date=_TRADING_DATE,
        trading_date=_TRADING_DATE,
        account_snapshot_id=_SNAPSHOT_ID,
        nav_basis=Decimal(100_000_000),
        session_open_nav=Decimal(100_000_000),
        automation_state=AutomationState.RUNNING,
        status="created",
        block_code=None,
        planned_at=_NOW,
        orders=(
            OrderRecord(
                client_order_id="a" * 32,
                sequence=1,
                symbol="005930",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=50,
                limit_price=Decimal(100_000),
                reference_price=Decimal(100_000),
                reference_source="KIS",
                reference_received_at=_NOW,
                state=OrderState.PLANNED,
                reject_code=None,
                decisions=(
                    RiskDecision(
                        rule=RiskRule.SYMBOL_EXPOSURE,
                        limit_value=Decimal(10_000_000),
                        projected_value=Decimal(5_000_000),
                        passed=True,
                    ),
                ),
            ),
            OrderRecord(
                client_order_id="b" * 32,
                sequence=2,
                symbol="069500",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=0,
                limit_price=None,
                reference_price=None,
                reference_source=None,
                reference_received_at=None,
                state=OrderState.REJECTED,
                reject_code="DATA_STALE",
                decisions=(),
            ),
        ),
    )


@final
class StubTradingReader:
    sectors: tuple[tuple[str, str], ...] = ()

    async def notification_status(self, environment: str) -> NotificationStatusRecord:
        _ = environment
        return NotificationStatusRecord(
            pending=3,
            failed=1,
            sent=12,
            oldest_pending_at=_NOW,
            recent=(
                NotificationEntryRecord(
                    kind="order_state",
                    severity="info",
                    state="sent",
                    attempts=1,
                    reason=None,
                    event_occurred_at=_NOW,
                ),
            ),
        )

    async def automation(self, environment: str) -> AutomationRecord | None:
        _ = environment
        return AutomationRecord(
            environment="paper",
            state=AutomationState.PAUSED,
            reason_code=RiskRule.DAILY_LOSS.value,
            trading_date=_TRADING_DATE,
            changed_at=_NOW,
        )

    async def automation_events(
        self,
        environment: str,
        limit: int,
    ) -> tuple[AutomationEventRecord, ...]:
        _ = (environment, limit)
        return (
            AutomationEventRecord(
                event_type="state_change",
                previous_state=AutomationState.RUNNING,
                state=AutomationState.PAUSED,
                reason_code=RiskRule.DAILY_LOSS.value,
                detail=None,
                occurred_at=_NOW,
            ),
            AutomationEventRecord(
                event_type="api_failure",
                previous_state=None,
                state=None,
                reason_code=None,
                detail="quote:TimeoutError",
                occurred_at=_NOW,
            ),
        )

    async def account_snapshots(
        self,
        environment: str,
        limit: int,
    ) -> tuple[StoredAccountSnapshot, ...]:
        _ = (environment, limit)
        return (
            StoredAccountSnapshot(
                snapshot_id=_SNAPSHOT_ID,
                snapshot=AccountSnapshot(
                    source="KIS",
                    environment="paper",
                    account_reference="abc123def456",
                    currency="KRW",
                    cash_balance=Decimal(89_020_000),
                    orderable_cash=Decimal(89_020_000),
                    position_value=Decimal(10_980_000),
                    nav=Decimal(100_000_000),
                    broker_position_value=Decimal(0),
                    broker_net_asset=Decimal(100_000_000),
                    trading_date=_TRADING_DATE,
                    as_of=_NOW,
                    received_at=_NOW,
                    positions=(
                        AccountPosition(
                            symbol="005930",
                            quantity=40,
                            orderable_quantity=40,
                            average_price=Decimal("268500.00000000"),
                            current_price=Decimal("274500.00000000"),
                            evaluation_amount=Decimal(10_980_000),
                            profit_loss=Decimal(240_000),
                        ),
                    ),
                ),
            ),
        )

    async def order_plans(self, environment: str, limit: int) -> tuple[OrderPlanSummary, ...]:
        _ = (environment, limit)
        return (OrderPlanSummary(plan=_plan(), order_count=2, rejected_count=1),)

    async def orders(self, environment: str, limit: int) -> tuple[OrderListEntry, ...]:
        _ = (environment, limit)
        plan = _plan()
        return tuple(
            OrderListEntry(
                client_order_id=order.client_order_id,
                plan_id=plan.plan_id,
                trading_date=plan.trading_date,
                created_at=_NOW,
                sequence=order.sequence,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                filled_quantity=0,
                limit_price=order.limit_price,
                reference_price=order.reference_price,
                reference_source=order.reference_source,
                reference_received_at=order.reference_received_at,
                state=order.state,
                reject_code=order.reject_code,
                broker_order_id="0000117057" if order.sequence == 1 else None,
                submitted_at=_NOW if order.sequence == 1 else None,
                average_fill_price=Decimal(100_000) if order.sequence == 1 else None,
            )
            for order in plan.orders
        )

    async def risk_state(
        self,
        environment: str,
        api_failure_window_seconds: int,
    ) -> TradingRiskState:
        _ = (environment, api_failure_window_seconds)
        snapshots = await self.account_snapshots(environment, 1)
        return TradingRiskState(
            evaluated_at=_NOW,
            basis_date=_TRADING_DATE,
            snapshot=snapshots[0],
            session_open_nav=Decimal(100_000_000),
            peak_nav=Decimal(100_000_000),
            max_order_amount=Decimal(5_000_000),
            sectors=self.sectors,
            counters=StoredCounters(
                open_orders=1,
                daily_order_attempts=6,
                daily_buy_amount=Decimal(12_000_000),
                consecutive_rejects=1,
                unreconciled_orders=True,
            ),
            api_failures=0,
        )

    async def order_plan(self, plan_id: UUID) -> OrderPlanRecord | None:
        return _plan() if plan_id == _PLAN_ID else None

    async def close(self) -> None:
        return None


def _client(
    sectors: tuple[tuple[str, str], ...] = (),
    now: datetime = _NOW,
) -> TestClient:
    def reader() -> StubTradingReader:
        stub = StubTradingReader()
        stub.sectors = sectors
        return stub

    app = create_app(
        automation_reset_factory=NoAutomationReset,
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        trading_reader_factory=reader,
        # 거래일 판정을 시각에 의존시키면 테스트가 실행 날짜에 따라 바뀐다. 주입한다.
        clock=lambda: now,
    )
    return TestClient(app)


def test_a_stale_trading_day_is_reported_as_disabled_without_rewriting_the_record() -> None:
    """정책 §6: 거래일이 바뀌면 상태는 DISABLED다.

    콘솔이 꺼진 자동매매를 가동 중으로 보여주면 안 된다. 조회는 쓰기를 하지 않으므로 저장된
    사실은 `stored_state`로 그대로 노출한다.
    """
    # 기록은 2026-08-18 거래일이고 조회 시각은 그 다음 거래일이다.
    response = _client(now=datetime(2026, 8, 19, 4, 0, tzinfo=UTC)).get("/api/trading/automation")

    assert response.status_code == 200
    payload = AutomationResponse.model_validate(response.json())
    assert payload.state == "disabled"
    assert payload.stored_state == "paused"
    assert payload.stale_reason_code == "TRADING_DAY_CHANGED"
    # 저장된 사유와 거래일은 그대로 남아 근거가 된다.
    assert payload.reason_code == "RISK_DAILY_LOSS"
    assert payload.trading_date == date(2026, 8, 18)


def test_automation_state_and_events_are_exposed() -> None:
    response = _client().get("/api/trading/automation")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "paper",
        "state": "paused",
        "stored_state": "paused",
        "stale_reason_code": None,
        "reason_code": "RISK_DAILY_LOSS",
        "trading_date": "2026-08-18",
        "changed_at": "2026-08-18T04:00:00Z",
        "events": [
            {
                "event_type": "state_change",
                "previous_state": "running",
                "state": "paused",
                "reason_code": "RISK_DAILY_LOSS",
                "detail": None,
                "occurred_at": "2026-08-18T04:00:00Z",
            },
            {
                "event_type": "api_failure",
                "previous_state": None,
                "state": None,
                "reason_code": None,
                "detail": "quote:TimeoutError",
                "occurred_at": "2026-08-18T04:00:00Z",
            },
        ],
    }


def test_account_snapshots_expose_hashed_reference_only() -> None:
    response = _client().get("/api/trading/account-snapshots?limit=5")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "paper",
        "snapshots": [
            {
                "snapshot_id": str(_SNAPSHOT_ID),
                "source": "KIS",
                "environment": "paper",
                "account_reference": "abc123def456",
                "currency": "KRW",
                "cash_balance": "89020000",
                "orderable_cash": "89020000",
                "position_value": "10980000",
                "nav": "100000000",
                "broker_net_asset": "100000000",
                "trading_date": "2026-08-18",
                "as_of": "2026-08-18T04:00:00Z",
                "received_at": "2026-08-18T04:00:00Z",
                "positions": [
                    {
                        "symbol": "005930",
                        "quantity": 40,
                        "orderable_quantity": 40,
                        "average_price": "268500.00000000",
                        "current_price": "274500.00000000",
                        "evaluation_amount": "10980000",
                        "profit_loss": "240000",
                    }
                ],
            }
        ],
    }
    assert "account_number" not in response.text


def test_order_plan_list_includes_counts() -> None:
    response = _client().get("/api/trading/order-plans")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "paper",
        "plans": [
            {
                "plan_id": str(_PLAN_ID),
                "strategy_name": "ma-rsi",
                "strategy_version": "1",
                "signal_date": "2026-08-18",
                "trading_date": "2026-08-18",
                "automation_state": "running",
                "status": "created",
                "block_code": None,
                "planned_at": "2026-08-18T04:00:00Z",
                "order_count": 2,
                "rejected_count": 1,
            }
        ],
    }


def test_order_plan_detail_includes_orders_and_risk_decisions() -> None:
    response = _client().get(f"/api/trading/order-plans/{_PLAN_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "plan_id": str(_PLAN_ID),
        "environment": "paper",
        "strategy_name": "ma-rsi",
        "strategy_version": "1",
        "parameters_json": '{"short_period":5}',
        "signal_date": "2026-08-18",
        "trading_date": "2026-08-18",
        "account_snapshot_id": str(_SNAPSHOT_ID),
        "nav_basis": "100000000",
        "session_open_nav": "100000000",
        "automation_state": "running",
        "status": "created",
        "block_code": None,
        "planned_at": "2026-08-18T04:00:00Z",
        "orders": [
            {
                "client_order_id": "a" * 32,
                "sequence": 1,
                "symbol": "005930",
                "side": "buy",
                "order_type": "limit",
                "quantity": 50,
                "limit_price": "100000",
                "reference_price": "100000",
                "reference_source": "KIS",
                "reference_received_at": "2026-08-18T04:00:00Z",
                "state": "planned",
                "reject_code": None,
                "risk_decisions": [
                    {
                        "rule_code": "RISK_SYMBOL_EXPOSURE",
                        "limit_value": "10000000",
                        "projected_value": "5000000",
                        "passed": True,
                    }
                ],
            },
            {
                "client_order_id": "b" * 32,
                "sequence": 2,
                "symbol": "069500",
                "side": "buy",
                "order_type": "limit",
                "quantity": 0,
                "limit_price": None,
                "reference_price": None,
                "reference_source": None,
                "reference_received_at": None,
                "state": "rejected",
                "reject_code": "DATA_STALE",
                "risk_decisions": [],
            },
        ],
    }


def test_order_list_exposes_stored_fill_quantity_and_plan_reference() -> None:
    response = _client().get("/api/trading/orders?limit=10")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "paper",
        "orders": [
            {
                "client_order_id": "a" * 32,
                "plan_id": str(_PLAN_ID),
                "trading_date": "2026-08-18",
                "created_at": "2026-08-18T04:00:00Z",
                "sequence": 1,
                "symbol": "005930",
                "side": "buy",
                "order_type": "limit",
                "quantity": 50,
                "filled_quantity": 0,
                "limit_price": "100000",
                "reference_price": "100000",
                "reference_source": "KIS",
                "reference_received_at": "2026-08-18T04:00:00Z",
                "state": "planned",
                "reject_code": None,
                "broker_order_id": "0000117057",
                "submitted_at": "2026-08-18T04:00:00Z",
                "average_fill_price": "100000",
            },
            {
                "client_order_id": "b" * 32,
                "plan_id": str(_PLAN_ID),
                "trading_date": "2026-08-18",
                "created_at": "2026-08-18T04:00:00Z",
                "sequence": 2,
                "symbol": "069500",
                "side": "buy",
                "order_type": "limit",
                "quantity": 0,
                "filled_quantity": 0,
                "limit_price": None,
                "reference_price": None,
                "reference_source": None,
                "reference_received_at": None,
                "state": "rejected",
                "reject_code": "DATA_STALE",
                "broker_order_id": None,
                "submitted_at": None,
                "average_fill_price": None,
            },
        ],
    }


def test_risk_limits_expose_policy_limits_with_current_usage() -> None:
    response = _client().get("/api/trading/risk-limits")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "paper",
        "evaluated_at": "2026-08-18T04:00:00Z",
        "basis_date": "2026-08-18",
        "snapshot_id": str(_SNAPSHOT_ID),
        "snapshot_as_of": "2026-08-18T04:00:00Z",
        "nav_basis": "100000000",
        "session_open_nav": "100000000",
        "peak_nav": "100000000",
        "items": [
            {
                "rule_code": "RISK_TOTAL_EXPOSURE",
                "basis": "nav_ratio",
                "comparison": "at_most",
                "limit_value": "0.80",
                "current_value": "0.109800",
                "usage_ratio": "0.137250",
                "reason": None,
            },
            {
                "rule_code": "RISK_MIN_CASH",
                "basis": "nav_ratio",
                "comparison": "at_least",
                "limit_value": "0.20",
                "current_value": "0.890200",
                "usage_ratio": "0.224669",
                "reason": None,
            },
            {
                "rule_code": "RISK_SYMBOL_EXPOSURE",
                "basis": "nav_ratio",
                "comparison": "at_most",
                "limit_value": "0.10",
                "current_value": "0.109800",
                "usage_ratio": "1.098000",
                "reason": None,
            },
            {
                "rule_code": "RISK_SECTOR_EXPOSURE",
                "basis": "nav_ratio",
                "comparison": "at_most",
                "limit_value": "0.30",
                "current_value": None,
                "usage_ratio": None,
                "reason": "MISSING_SECTOR_DATA",
            },
            {
                "rule_code": "RISK_UNCLASSIFIED_EXPOSURE",
                "basis": "nav_ratio",
                "comparison": "at_most",
                "limit_value": "0.10",
                "current_value": "0.109800",
                "usage_ratio": "1.098000",
                "reason": None,
            },
            {
                "rule_code": "RISK_ORDER_AMOUNT",
                "basis": "nav_ratio",
                "comparison": "at_most",
                "limit_value": "0.05",
                "current_value": "0.050000",
                "usage_ratio": "1.000000",
                "reason": None,
            },
            {
                "rule_code": "RISK_DAILY_BUY_AMOUNT",
                "basis": "session_open_nav_ratio",
                "comparison": "at_most",
                "limit_value": "0.20",
                "current_value": "0.120000",
                "usage_ratio": "0.600000",
                "reason": None,
            },
            {
                "rule_code": "RISK_OPEN_ORDERS",
                "basis": "count",
                "comparison": "at_most",
                "limit_value": "5",
                "current_value": "1",
                "usage_ratio": "0.200000",
                "reason": None,
            },
            {
                "rule_code": "RISK_DAILY_ORDER_ATTEMPTS",
                "basis": "count",
                "comparison": "at_most",
                "limit_value": "20",
                "current_value": "6",
                "usage_ratio": "0.300000",
                "reason": None,
            },
            {
                "rule_code": "RISK_DAILY_LOSS",
                "basis": "session_open_nav_ratio",
                "comparison": "at_least",
                "limit_value": "-0.02",
                "current_value": "0.000000",
                "usage_ratio": "0.000000",
                "reason": None,
            },
            {
                "rule_code": "RISK_DRAWDOWN",
                "basis": "peak_nav_ratio",
                "comparison": "at_least",
                "limit_value": "-0.05",
                "current_value": "0.000000",
                "usage_ratio": "0.000000",
                "reason": None,
            },
            {
                "rule_code": "RISK_CONSECUTIVE_REJECTS",
                "basis": "count",
                "comparison": "at_most",
                "limit_value": "3",
                "current_value": "1",
                "usage_ratio": "0.333333",
                "reason": None,
            },
            {
                "rule_code": "RISK_API_FAILURES",
                "basis": "count",
                "comparison": "at_most",
                "limit_value": "3",
                "current_value": "0",
                "usage_ratio": "0.000000",
                "reason": None,
            },
        ],
        "conditions": {
            "order_window_start": "09:05:00",
            "order_window_end": "15:15:00",
            "quote_max_age_seconds": 10,
            "price_band": "0.01",
            "api_failure_window_seconds": 300,
        },
    }


def test_unknown_plan_returns_404_and_invalid_id_returns_422() -> None:
    client = _client()

    assert client.get(f"/api/trading/order-plans/{_MISSING_PLAN_ID}").status_code == 404
    assert client.get("/api/trading/order-plans/not-a-uuid").status_code == 422
    assert client.get("/api/trading/account-snapshots?limit=0").status_code == 422
    assert client.get("/api/trading/orders?limit=0").status_code == 422


def test_sector_usage_is_reported_once_sector_facts_exist() -> None:
    """업종 사실이 생기면 업종 한도가 값을 갖고 미분류는 비어야 한다(종목 유니버스 계약)."""
    response = _client(sectors=(("005930", "5"),)).get("/api/trading/risk-limits")

    assert response.status_code == 200
    body = cast("dict[str, list[dict[str, str | None]]]", response.json())
    usage = {item["rule_code"]: item for item in body["items"]}
    assert usage["RISK_SECTOR_EXPOSURE"] == {
        "rule_code": "RISK_SECTOR_EXPOSURE",
        "basis": "nav_ratio",
        "comparison": "at_most",
        "limit_value": "0.30",
        "current_value": "0.109800",
        "usage_ratio": "0.366000",
        "reason": None,
    }
    assert usage["RISK_UNCLASSIFIED_EXPOSURE"] == {
        "rule_code": "RISK_UNCLASSIFIED_EXPOSURE",
        "basis": "nav_ratio",
        "comparison": "at_most",
        "limit_value": "0.10",
        "current_value": "0.000000",
        "usage_ratio": "0.000000",
        "reason": None,
    }


@final
@dataclass
class StubAutomationReset:
    """기동 리셋 대상 저장소. API가 기동할 때 정확히 한 번 호출돼야 한다."""

    state: AutomationState = AutomationState.RUNNING
    transitions: list[AutomationTransition] = field(default_factory=list)
    closed: bool = False

    async def automation_record(self, environment: str) -> AutomationRecord | None:
        return AutomationRecord(
            environment=environment,
            state=self.state,
            reason_code="USER_COMMAND",
            trading_date=_TRADING_DATE,
            changed_at=_NOW,
        )

    async def transition_automation(self, transition: AutomationTransition) -> AutomationRecord:
        self.transitions.append(transition)
        self.state = transition.requested
        return AutomationRecord(
            environment=transition.environment,
            state=transition.requested,
            reason_code=transition.reason_code,
            trading_date=transition.trading_date,
            changed_at=transition.occurred_at,
        )

    async def close(self) -> None:
        self.closed = True


def test_starting_the_api_returns_automation_to_disabled() -> None:
    """정책 §6: 서버 재시작은 상태를 되돌린다. 2026-08-24 실측에서 `running`이 살아남았다."""
    reset = StubAutomationReset()

    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        trading_reader_factory=StubTradingReader,
        automation_reset_factory=lambda: reset,
        clock=lambda: _NOW,
    )
    with TestClient(app):
        pass

    (transition,) = reset.transitions
    assert transition.requested is AutomationState.DISABLED
    assert transition.reason_code == "PROCESS_START"
    assert reset.closed is True


_UNAVAILABLE = "database unavailable"


@final
class FailingAutomationReset:
    """DB에 닿지 못하는 기동 리셋."""

    async def automation_record(self, environment: str) -> AutomationRecord | None:
        _ = environment
        raise ConnectionError(_UNAVAILABLE)

    async def transition_automation(self, transition: AutomationTransition) -> AutomationRecord:
        raise AssertionError(transition)

    async def close(self) -> None:
        return None


def test_the_api_refuses_to_start_when_the_automation_reset_fails() -> None:
    """리셋을 적용하지 못하면 기동하지 않는다.

    돌려보낼 수 없는 상태로 서버를 열면 어제 켠 `running`이 살아 있는 채로 서비스된다. 기동 실패는
    컨테이너가 재시작을 반복하는 형태로 드러나고, DB가 돌아오면 리셋이 적용된다.
    """
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        trading_reader_factory=StubTradingReader,
        automation_reset_factory=FailingAutomationReset,
        clock=lambda: _NOW,
    )

    with pytest.raises(ConnectionError), TestClient(app):
        pass


def test_the_notifications_endpoint_reports_pending_and_failed_counts() -> None:
    """콘솔이 '알림이 조용한 것'과 '보낼 것이 없는 것'을 구분할 수 있어야 한다."""
    response = _client().get("/api/trading/notifications")

    assert response.status_code == 200
    payload = NotificationStatusResponse.model_validate(response.json())
    assert payload.pending == 3
    assert payload.failed == 1
    assert payload.sent_today == 12
    assert payload.oldest_pending_at is not None
    assert len(payload.recent) == 1
    assert payload.recent[0].kind == "order_state"
    # 금지 필드가 조회 응답에도 없어야 한다(계약 §조회).
    body = response.text
    assert "nav" not in body.lower()
    assert "account" not in body.lower()
