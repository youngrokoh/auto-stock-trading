from decimal import Decimal

import anyio
from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_account import (
    BALANCE_ENDPOINT,
    KisAccount,
    KisAccountAdapter,
)
from auto_stock_trading.domain.market_data.models import BrokerOperation
from auto_stock_trading.domain.orders.account import account_reference
from tests.brokers.kis_fixture import create_fixture_handler_client

_ACCOUNT = KisAccount(number=SecretStr("50000000"), product_code=SecretStr("01"))


def test_balance_snapshot_normalizes_cash_positions_and_nav() -> None:
    async def run() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisAccountAdapter(client, _ACCOUNT, paper=True)
        try:
            observation = await adapter.fetch_balance()
        finally:
            await adapter.close()

        request = handler.market_requests[-1]
        assert request.url.path == BALANCE_ENDPOINT
        assert request.headers["tr_id"] == "VTTC8434R"

        snapshot = observation.snapshot
        assert snapshot.cash_balance == Decimal(89_020_000)
        assert snapshot.orderable_cash == Decimal(89_020_000)
        assert snapshot.position_value == Decimal(10_980_000)
        assert snapshot.nav == Decimal(100_000_000)
        assert snapshot.broker_net_asset == Decimal(100_000_000)
        assert snapshot.currency == "KRW"
        assert snapshot.source == "KIS"
        assert snapshot.environment == "paper"

    anyio.run(run)


def test_balance_snapshot_drops_zero_quantity_holdings() -> None:
    async def run() -> None:
        client, _ = create_fixture_handler_client()
        adapter = KisAccountAdapter(client, _ACCOUNT, paper=True)
        try:
            observation = await adapter.fetch_balance()
        finally:
            await adapter.close()

        (position,) = observation.snapshot.positions
        assert position.symbol == "005930"
        assert position.quantity == 40
        assert position.orderable_quantity == 40
        assert position.average_price == Decimal("268500.0000")
        assert position.current_price == Decimal(274_500)
        assert position.evaluation_amount == Decimal(10_980_000)
        assert position.profit_loss == Decimal(240_000)

    anyio.run(run)


def test_raw_response_keeps_account_number_out_of_the_fingerprint() -> None:
    async def run() -> None:
        client, _ = create_fixture_handler_client()
        adapter = KisAccountAdapter(client, _ACCOUNT, paper=True)
        try:
            observation = await adapter.fetch_balance()
        finally:
            await adapter.close()

        reference = account_reference("50000000", "01")
        assert observation.raw.operation is BrokerOperation.ACCOUNT_BALANCE
        assert observation.raw.request_fingerprint == f"account_balance:{reference}"
        assert "50000000" not in observation.raw.request_fingerprint
        assert observation.snapshot.account_reference == reference
        assert len(reference) == 12

    anyio.run(run)


def test_nav_uses_settlement_adjusted_cash_and_matches_the_broker() -> None:
    """정책 §2: NAV는 현금에서 미결제 비용을 뺀 값에 평가금액을 더한다."""

    async def scenario() -> None:
        client, _ = create_fixture_handler_client(
            balance_filename="account_balance_holding.json",
        )
        adapter = KisAccountAdapter(client, _ACCOUNT, paper=True)
        try:
            observation = await adapter.fetch_balance()
        finally:
            await adapter.close()

        snapshot = observation.snapshot
        assert snapshot.cash_balance == Decimal(10_000_000)
        assert snapshot.orderable_cash == Decimal(9_004_860)
        assert snapshot.position_value == Decimal(994_000)
        assert snapshot.nav == Decimal(9_998_860)
        assert snapshot.nav == snapshot.broker_net_asset
        (position,) = snapshot.positions
        assert position.symbol == "005930"
        assert position.quantity == 4
        assert position.orderable_quantity == 4
        assert position.average_price == Decimal("248750.0000")
        assert position.current_price == Decimal(248_500)
        assert position.evaluation_amount == Decimal(994_000)
        assert position.profit_loss == Decimal(-1_000)

    anyio.run(scenario)
