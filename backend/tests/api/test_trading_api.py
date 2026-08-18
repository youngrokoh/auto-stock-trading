from datetime import UTC, date, datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
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
    OrderPlanRecord,
    OrderPlanSummary,
    OrderRecord,
    StoredAccountSnapshot,
)
from auto_stock_trading.domain.risk.engine import RiskDecision
from auto_stock_trading.domain.risk.limits import RiskRule
from auto_stock_trading.settings.runtime import Environment, Settings

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

    async def order_plan(self, plan_id: UUID) -> OrderPlanRecord | None:
        return _plan() if plan_id == _PLAN_ID else None

    async def close(self) -> None:
        return None


def _client() -> TestClient:
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        trading_reader_factory=StubTradingReader,
    )
    return TestClient(app)


def test_automation_state_and_events_are_exposed() -> None:
    response = _client().get("/api/trading/automation")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "paper",
        "state": "paused",
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


def test_unknown_plan_returns_404_and_invalid_id_returns_422() -> None:
    client = _client()

    assert client.get(f"/api/trading/order-plans/{_MISSING_PLAN_ID}").status_code == 404
    assert client.get("/api/trading/order-plans/not-a-uuid").status_code == 422
    assert client.get("/api/trading/account-snapshots?limit=0").status_code == 422
