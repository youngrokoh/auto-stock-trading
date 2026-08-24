from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import anyio
import pytest
from pydantic import RootModel, SecretStr

from auto_stock_trading.adapters.brokers.kis_account import KisAccount
from auto_stock_trading.adapters.brokers.kis_orders import (
    CancelRequest,
    KisOrderAdapter,
    OrderSubmission,
)
from auto_stock_trading.domain.orders.models import OrderSide
from tests.brokers.kis_fixture import create_fixture_handler_client

if TYPE_CHECKING:
    import httpx2


class KisOrderBody(RootModel[dict[str, str]]):
    """주문 본문은 KIS 계약상 모든 값이 문자열이다."""


def _body(request: httpx2.Request) -> dict[str, str]:
    """요청 본문을 문자열 사전으로 읽는다. KIS 주문 본문은 모든 값이 문자열이다."""
    return KisOrderBody.model_validate_json(request.content.decode()).root


_ACCOUNT: Final = KisAccount(number=SecretStr("50123456"), product_code=SecretStr("01"))
_TRADING_DATE: Final = date(2026, 8, 19)
_SUBMISSION: Final = OrderSubmission(
    symbol="005930",
    side=OrderSide.BUY,
    quantity=3,
    limit_price=Decimal(71_800),
)


def test_submitted_order_returns_broker_identifiers_and_keeps_the_account_hidden() -> None:
    async def scenario() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        try:
            acknowledgement = await adapter.submit(_SUBMISSION)
        finally:
            await adapter.close()

        assert acknowledgement.accepted is True
        assert acknowledgement.broker_order_id == "0000117057"
        assert acknowledgement.broker_org_no == "00950"
        assert acknowledgement.broker_order_time == "101153"
        assert acknowledgement.message_code == "APBK0013"
        (request,) = handler.market_requests
        assert request.method == "POST"
        assert request.headers["tr_id"] == "VTTC0802U"
        body = _body(request)
        assert body["PDNO"] == "005930"
        assert body["ORD_DVSN"] == "00"
        assert body["ORD_QTY"] == "3"
        assert body["ORD_UNPR"] == "71800"
        assert body["CANO"] == "50123456"
        raw = acknowledgement.raw
        assert raw.request_fingerprint == f"order_submit:{_ACCOUNT.reference}:005930:buy:3"
        assert "50123456" not in raw.request_fingerprint

    anyio.run(scenario)


def test_sell_order_uses_the_paper_sell_transaction_id() -> None:
    async def scenario() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        try:
            _ = await adapter.submit(
                OrderSubmission(
                    symbol="005930",
                    side=OrderSide.SELL,
                    quantity=1,
                    limit_price=Decimal(71_000),
                )
            )
        finally:
            await adapter.close()

        (request,) = handler.market_requests
        assert request.headers["tr_id"] == "VTTC0801U"

    anyio.run(scenario)


def test_rejected_order_is_reported_without_raising() -> None:
    async def scenario() -> None:
        client, _ = create_fixture_handler_client(order_filename="order_cash_rejected.json")
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        try:
            acknowledgement = await adapter.submit(_SUBMISSION)
        finally:
            await adapter.close()

        assert acknowledgement.accepted is False
        assert acknowledgement.broker_order_id is None
        assert acknowledgement.message_code == "APBK0919"
        assert acknowledgement.message == "주문가능금액이 부족합니다."

    anyio.run(scenario)


def test_cancel_sends_the_broker_identifiers_and_cancel_division() -> None:
    async def scenario() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        try:
            acknowledgement = await adapter.cancel(
                CancelRequest(broker_org_no="00950", broker_order_id="0000117057", quantity=2)
            )
        finally:
            await adapter.close()

        assert acknowledgement.accepted is True
        (request,) = handler.market_requests
        assert request.headers["tr_id"] == "VTTC0803U"
        body = _body(request)
        assert body["KRX_FWDG_ORD_ORGNO"] == "00950"
        assert body["ORGN_ODNO"] == "0000117057"
        assert body["RVSE_CNCL_DVSN_CD"] == "02"
        assert body["QTY_ALL_ORD_YN"] == "Y"
        assert body["ORD_UNPR"] == "0"

    anyio.run(scenario)


def test_daily_fills_are_normalized_from_broker_rows() -> None:
    async def scenario() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        try:
            observation = await adapter.fetch_daily_fills(_TRADING_DATE)
        finally:
            await adapter.close()

        (request,) = handler.market_requests
        assert request.headers["tr_id"] == "VTTC8001R"
        assert "INQR_STRT_DT=20260819" in request.url.query.decode()
        first, second = observation.fills
        assert first.broker_order_id == "0000117057"
        assert first.symbol == "005930"
        assert first.order_quantity == 3
        assert first.filled_quantity == 1
        assert first.remaining_quantity == 2
        assert first.rejected_quantity == 0
        assert first.canceled is False
        assert first.average_fill_price == Decimal("71800.0000")
        assert second.canceled is True
        assert second.filled_quantity == 0
        assert second.average_fill_price is None
        assert observation.raw.request_fingerprint == (
            f"order_fills:{_ACCOUNT.reference}:2026-08-19"
        )

    anyio.run(scenario)


def test_empty_daily_fills_are_not_an_error() -> None:
    async def scenario() -> None:
        client, _ = create_fixture_handler_client(fills_filename="daily_fills_empty.json")
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        try:
            observation = await adapter.fetch_daily_fills(_TRADING_DATE)
        finally:
            await adapter.close()

        assert observation.fills == ()

    anyio.run(scenario)


def test_live_environment_uses_live_transaction_ids() -> None:
    async def scenario() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=False)
        try:
            _ = await adapter.submit(_SUBMISSION)
        finally:
            await adapter.close()

        (request,) = handler.market_requests
        assert request.headers["tr_id"] == "TTTC0802U"

    anyio.run(scenario)


def test_received_at_is_recorded_in_utc() -> None:
    async def scenario() -> None:
        client, _ = create_fixture_handler_client()
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        before = datetime.now(UTC)
        try:
            acknowledgement = await adapter.submit(_SUBMISSION)
        finally:
            await adapter.close()

        assert acknowledgement.raw.received_at >= before
        assert acknowledgement.raw.received_at.tzinfo is not None

    anyio.run(scenario)


def test_unparsable_response_fails_closed() -> None:
    async def scenario() -> None:
        client, _ = create_fixture_handler_client(order_filename="order_cash_broken.json")
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        try:
            with pytest.raises(Exception, match="contract"):
                _ = await adapter.submit(_SUBMISSION)
        finally:
            await adapter.close()

    anyio.run(scenario)


def test_a_partial_cancel_sends_the_quantity_and_the_partial_flag() -> None:
    """실측(2026-08-24): `QTY_ALL_ORD_YN="N"` + 명시 `ORD_QTY`가 취소할 수량이다.

    전량 플래그를 고정으로 보내면 수량을 지정할 자리가 없다 — 부분 취소가 막혀 있던 이유다.
    """

    async def scenario() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisOrderAdapter(client, _ACCOUNT, paper=True)
        try:
            acknowledgement = await adapter.cancel(
                CancelRequest(
                    broker_org_no="00950",
                    broker_order_id="0000117057",
                    quantity=5,
                    partial=True,
                )
            )
        finally:
            await adapter.close()

        assert acknowledgement.accepted is True
        (request,) = handler.market_requests
        body = _body(request)
        assert body["RVSE_CNCL_DVSN_CD"] == "02"
        assert body["QTY_ALL_ORD_YN"] == "N"
        assert body["ORD_QTY"] == "5"

    anyio.run(scenario)
