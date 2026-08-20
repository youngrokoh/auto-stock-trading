from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Protocol, final
from zoneinfo import ZoneInfo

from auto_stock_trading.adapters.brokers.kis_contracts import KisContract
from auto_stock_trading.adapters.brokers.kis_mapping import parse_response, raw_from
from auto_stock_trading.domain.market_data.models import BrokerOperation
from auto_stock_trading.domain.orders.account import (
    AccountPosition,
    AccountSnapshot,
    AccountSnapshotObservation,
    account_reference,
)

if TYPE_CHECKING:
    from pydantic import SecretStr

    from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient

BALANCE_ENDPOINT: Final = "/uapi/domestic-stock/v1/trading/inquire-balance"
_PAPER_BALANCE_TR: Final = "VTTC8434R"
_LIVE_BALANCE_TR: Final = "TTTC8434R"
_SEOUL: Final = ZoneInfo("Asia/Seoul")
_SOURCE: Final = "KIS"
_CURRENCY: Final = "KRW"


@dataclass(frozen=True, slots=True)
class KisAccount:
    """계좌번호 원문은 secret에서만 오고 로그·저장소·응답에 남기지 않는다."""

    number: SecretStr
    product_code: SecretStr

    @property
    def reference(self) -> str:
        return account_reference(
            self.number.get_secret_value(),
            self.product_code.get_secret_value(),
        )


class KisBalanceHolding(KisContract):
    pdno: str
    hldg_qty: str
    ord_psbl_qty: str
    pchs_avg_pric: str
    prpr: str
    evlu_amt: str
    evlu_pfls_amt: str


class KisBalanceSummary(KisContract):
    dnca_tot_amt: str
    prvs_rcdl_excc_amt: str
    scts_evlu_amt: str
    tot_evlu_amt: str
    nass_amt: str


class KisBalanceResponse(KisContract):
    rt_cd: str
    msg_cd: str
    msg1: str
    output1: tuple[KisBalanceHolding, ...] = ()
    output2: tuple[KisBalanceSummary, ...] = ()


class AccountSource(Protocol):
    async def fetch_balance(self) -> AccountSnapshotObservation: ...

    async def close(self) -> None: ...


def _position(holding: KisBalanceHolding) -> AccountPosition:
    quantity = int(holding.hldg_qty)
    return AccountPosition(
        symbol=holding.pdno,
        quantity=quantity,
        orderable_quantity=min(int(holding.ord_psbl_qty), quantity),
        average_price=Decimal(holding.pchs_avg_pric),
        current_price=Decimal(holding.prpr),
        evaluation_amount=Decimal(holding.evlu_amt),
        profit_loss=Decimal(holding.evlu_pfls_amt),
    )


@final
class KisAccountAdapter:
    """KIS 국내주식 잔고조회(읽기 전용) 어댑터. 주문 API는 포함하지 않는다."""

    def __init__(self, client: KisHttpClient, account: KisAccount, *, paper: bool) -> None:
        self._client = client
        self._account = account
        self._transaction_id = _PAPER_BALANCE_TR if paper else _LIVE_BALANCE_TR
        self._environment = "paper" if paper else "live"

    async def fetch_balance(self) -> AccountSnapshotObservation:
        raw = await self._client.get(
            endpoint=BALANCE_ENDPOINT,
            transaction_id=self._transaction_id,
            params={
                "CANO": self._account.number.get_secret_value(),
                "ACNT_PRDT_CD": self._account.product_code.get_secret_value(),
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            request_fingerprint=f"account_balance:{self._account.reference}",
        )
        response = parse_response(raw, KisBalanceResponse, BrokerOperation.ACCOUNT_BALANCE)
        summary = response.output2[0] if response.output2 else None
        if summary is None:
            raise KisAccountContractError
        positions = tuple(
            _position(holding) for holding in response.output1 if int(holding.hldg_qty) > 0
        )
        cash_balance = Decimal(summary.dnca_tot_amt)
        # 정책 §2의 기준 NAV는 "현금에서 미결제 비용을 뺀 값"을 쓴다. 예수금 총액은 미결제 매수분을
        # 아직 차감하지 않으므로 가수도정산금액(D+2 예수금)을 NAV의 현금으로 사용한다.
        settled_cash = Decimal(summary.prvs_rcdl_excc_amt)
        position_value = sum(
            (position.evaluation_amount for position in positions),
            Decimal(0),
        )
        snapshot = AccountSnapshot(
            source=_SOURCE,
            environment=self._environment,
            account_reference=self._account.reference,
            currency=_CURRENCY,
            cash_balance=cash_balance,
            orderable_cash=settled_cash,
            position_value=position_value,
            nav=settled_cash + position_value,
            broker_position_value=Decimal(summary.scts_evlu_amt),
            broker_net_asset=Decimal(summary.nass_amt),
            trading_date=raw.received_at.astimezone(_SEOUL).date(),
            as_of=raw.received_at,
            received_at=raw.received_at,
            positions=positions,
        )
        return AccountSnapshotObservation(
            snapshot=snapshot,
            raw=raw_from(BrokerOperation.ACCOUNT_BALANCE, raw),
        )

    async def close(self) -> None:
        await self._client.close()


class KisAccountContractError(Exception):
    """잔고조회 응답에 계좌 요약(output2)이 없다."""
