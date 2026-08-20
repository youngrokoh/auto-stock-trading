"""KIS 주문 제출·취소·일별주문체결 조회. 계좌번호 원문은 요청 본문에만 쓰고 저장하지 않는다."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final

from pydantic import ValidationError

from auto_stock_trading.adapters.brokers.kis_contracts import KisContract
from auto_stock_trading.adapters.brokers.kis_mapping import KisContractError, raw_from
from auto_stock_trading.domain.market_data.models import BrokerOperation
from auto_stock_trading.domain.orders.fills import BrokerFill
from auto_stock_trading.domain.orders.models import OrderSide

if TYPE_CHECKING:
    from datetime import date

    from auto_stock_trading.adapters.brokers.kis_account import KisAccount
    from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient
    from auto_stock_trading.domain.market_data.models import RawBrokerResponse

ORDER_ENDPOINT: Final = "/uapi/domestic-stock/v1/trading/order-cash"
REVISE_CANCEL_ENDPOINT: Final = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
DAILY_FILLS_ENDPOINT: Final = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

_PAPER_BUY_TR: Final = "VTTC0802U"
_PAPER_SELL_TR: Final = "VTTC0801U"
_LIVE_BUY_TR: Final = "TTTC0802U"
_LIVE_SELL_TR: Final = "TTTC0801U"
_PAPER_CANCEL_TR: Final = "VTTC0803U"
_LIVE_CANCEL_TR: Final = "TTTC0803U"
_PAPER_FILLS_TR: Final = "VTTC8001R"
_LIVE_FILLS_TR: Final = "TTTC8001R"

_LIMIT_ORDER_DIVISION: Final = "00"
_CANCEL_DIVISION: Final = "02"
_REVISE_DIVISION: Final = "01"
_ALL_QUANTITY: Final = "Y"
_CANCELED: Final = "Y"


class KisOrderOutput(KisContract):
    KRX_FWDG_ORD_ORGNO: str
    ODNO: str
    ORD_TMD: str


class KisOrderResponse(KisContract):
    rt_cd: str
    msg_cd: str
    msg1: str
    output: KisOrderOutput | None = None


class KisFillRow(KisContract):
    odno: str
    pdno: str
    ord_qty: str
    tot_ccld_qty: str
    rmn_qty: str
    rjct_qty: str
    cncl_yn: str
    avg_prvs: str


class KisDailyFillsResponse(KisContract):
    rt_cd: str
    msg_cd: str
    msg1: str
    output1: tuple[KisFillRow, ...] = ()


@dataclass(frozen=True, slots=True)
class OrderSubmission:
    symbol: str
    side: OrderSide
    quantity: int
    limit_price: Decimal


@dataclass(frozen=True, slots=True)
class CancelRequest:
    broker_org_no: str
    broker_order_id: str
    quantity: int


@dataclass(frozen=True, slots=True)
class ReviseRequest:
    """정정 요청. 수량은 잔여 수량 그대로이고 지정가만 바뀐다(ADR-0011 결정 2)."""

    broker_org_no: str
    broker_order_id: str
    quantity: int
    limit_price: Decimal


@dataclass(frozen=True, slots=True)
class BrokerAcknowledgement:
    """증권사 접수 결과. 거절도 예외가 아니라 사실로 돌려준다."""

    accepted: bool
    broker_order_id: str | None
    broker_org_no: str | None
    broker_order_time: str | None
    message_code: str
    message: str
    raw: RawBrokerResponse


@dataclass(frozen=True, slots=True)
class DailyFillsObservation:
    fills: tuple[BrokerFill, ...]
    raw: RawBrokerResponse


def _int(value: str) -> int:
    return int(value or "0")


def _price(value: str) -> Decimal | None:
    if not value:
        return None
    price = Decimal(value)
    return price if price > 0 else None


def _won(value: Decimal) -> str:
    return str(value.quantize(Decimal(1)))


def _validate[ResponseT: KisContract](
    payload_json: str,
    response_type: type[ResponseT],
    operation: BrokerOperation,
) -> ResponseT:
    try:
        return response_type.model_validate_json(payload_json)
    except ValidationError as error:
        raise KisContractError(operation) from error


def _acknowledgement(
    response: KisOrderResponse,
    raw: RawBrokerResponse,
) -> BrokerAcknowledgement:
    output = response.output
    accepted = response.rt_cd == "0" and output is not None and bool(output.ODNO)
    return BrokerAcknowledgement(
        accepted=accepted,
        broker_order_id=output.ODNO if accepted and output is not None else None,
        broker_org_no=output.KRX_FWDG_ORD_ORGNO if accepted and output is not None else None,
        broker_order_time=output.ORD_TMD if accepted and output is not None else None,
        message_code=response.msg_cd,
        message=response.msg1.strip(),
        raw=raw,
    )


@final
class KisOrderAdapter:
    def __init__(self, client: KisHttpClient, account: KisAccount, *, paper: bool) -> None:
        self._client = client
        self._account = account
        self._paper = paper

    async def submit(self, submission: OrderSubmission) -> BrokerAcknowledgement:
        transaction_id = self._order_transaction_id(submission.side)
        fingerprint = (
            f"order_submit:{self._account.reference}:{submission.symbol}"
            f":{submission.side.value}:{submission.quantity}"
        )
        raw_response = await self._client.post(
            endpoint=ORDER_ENDPOINT,
            transaction_id=transaction_id,
            body={
                **self._account_body(),
                "PDNO": submission.symbol,
                "ORD_DVSN": _LIMIT_ORDER_DIVISION,
                "ORD_QTY": str(submission.quantity),
                "ORD_UNPR": _won(submission.limit_price),
            },
            request_fingerprint=fingerprint,
        )
        response = _validate(
            raw_response.payload_json,
            KisOrderResponse,
            BrokerOperation.ORDER_SUBMIT,
        )
        return _acknowledgement(response, raw_from(BrokerOperation.ORDER_SUBMIT, raw_response))

    async def cancel(self, request: CancelRequest) -> BrokerAcknowledgement:
        transaction_id = _PAPER_CANCEL_TR if self._paper else _LIVE_CANCEL_TR
        fingerprint = f"order_cancel:{self._account.reference}:{request.broker_order_id}"
        raw_response = await self._client.post(
            endpoint=REVISE_CANCEL_ENDPOINT,
            transaction_id=transaction_id,
            body={
                **self._account_body(),
                "KRX_FWDG_ORD_ORGNO": request.broker_org_no,
                "ORGN_ODNO": request.broker_order_id,
                "ORD_DVSN": _LIMIT_ORDER_DIVISION,
                "RVSE_CNCL_DVSN_CD": _CANCEL_DIVISION,
                "ORD_QTY": str(request.quantity),
                "ORD_UNPR": "0",
                "QTY_ALL_ORD_YN": _ALL_QUANTITY,
            },
            request_fingerprint=fingerprint,
        )
        response = _validate(
            raw_response.payload_json,
            KisOrderResponse,
            BrokerOperation.ORDER_CANCEL,
        )
        return _acknowledgement(response, raw_from(BrokerOperation.ORDER_CANCEL, raw_response))

    async def revise(self, request: ReviseRequest) -> BrokerAcknowledgement:
        """지정가 정정. 취소와 같은 엔드포인트이며 구분코드만 다르다."""
        transaction_id = _PAPER_CANCEL_TR if self._paper else _LIVE_CANCEL_TR
        fingerprint = f"order_revise:{self._account.reference}:{request.broker_order_id}"
        raw_response = await self._client.post(
            endpoint=REVISE_CANCEL_ENDPOINT,
            transaction_id=transaction_id,
            body={
                **self._account_body(),
                "KRX_FWDG_ORD_ORGNO": request.broker_org_no,
                "ORGN_ODNO": request.broker_order_id,
                "ORD_DVSN": _LIMIT_ORDER_DIVISION,
                "RVSE_CNCL_DVSN_CD": _REVISE_DIVISION,
                "ORD_QTY": str(request.quantity),
                "ORD_UNPR": f"{request.limit_price:.0f}",
                "QTY_ALL_ORD_YN": _ALL_QUANTITY,
            },
            request_fingerprint=fingerprint,
        )
        response = _validate(
            raw_response.payload_json,
            KisOrderResponse,
            BrokerOperation.ORDER_CANCEL,
        )
        return _acknowledgement(response, raw_from(BrokerOperation.ORDER_CANCEL, raw_response))

    async def fetch_daily_fills(self, trading_date: date) -> DailyFillsObservation:
        transaction_id = _PAPER_FILLS_TR if self._paper else _LIVE_FILLS_TR
        day = trading_date.strftime("%Y%m%d")
        raw_response = await self._client.get(
            endpoint=DAILY_FILLS_ENDPOINT,
            transaction_id=transaction_id,
            params={
                **self._account_body(),
                "INQR_STRT_DT": day,
                "INQR_END_DT": day,
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": "",
                "CCLD_DVSN": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            request_fingerprint=f"order_fills:{self._account.reference}:{trading_date.isoformat()}",
        )
        response = _validate(
            raw_response.payload_json,
            KisDailyFillsResponse,
            BrokerOperation.ORDER_FILLS,
        )
        return DailyFillsObservation(
            fills=tuple(_fill(row) for row in response.output1),
            raw=raw_from(BrokerOperation.ORDER_FILLS, raw_response),
        )

    async def close(self) -> None:
        await self._client.close()

    def _order_transaction_id(self, side: OrderSide) -> str:
        if side is OrderSide.BUY:
            return _PAPER_BUY_TR if self._paper else _LIVE_BUY_TR
        return _PAPER_SELL_TR if self._paper else _LIVE_SELL_TR

    def _account_body(self) -> dict[str, str]:
        return {
            "CANO": self._account.number.get_secret_value(),
            "ACNT_PRDT_CD": self._account.product_code.get_secret_value(),
        }


def _fill(row: KisFillRow) -> BrokerFill:
    return BrokerFill(
        broker_order_id=row.odno,
        symbol=row.pdno,
        order_quantity=_int(row.ord_qty),
        filled_quantity=_int(row.tot_ccld_qty),
        remaining_quantity=_int(row.rmn_qty),
        rejected_quantity=_int(row.rjct_qty),
        canceled=row.cncl_yn.strip().upper() == _CANCELED,
        average_fill_price=_price(row.avg_prvs),
    )
