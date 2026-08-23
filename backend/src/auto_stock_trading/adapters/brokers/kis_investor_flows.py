from datetime import date, datetime
from typing import TYPE_CHECKING, Final, Protocol, final
from zoneinfo import ZoneInfo

from auto_stock_trading.adapters.brokers.kis_contracts import (
    KisInvestorResponse,
    KisInvestorRow,
)
from auto_stock_trading.adapters.brokers.kis_mapping import (
    KIS_SOURCE,
    parse_response,
    raw_from,
)
from auto_stock_trading.domain.market_data.investor_flows import (
    InvestorFlow,
    InvestorFlowBundle,
)
from auto_stock_trading.domain.market_data.models import BrokerOperation

if TYPE_CHECKING:
    from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient
    from auto_stock_trading.domain.market_data.models import InstrumentTarget

INVESTOR_FLOWS_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-investor"
_TRANSACTION_ID: Final = "FHKST01010900"
_SEOUL: Final = ZoneInfo("Asia/Seoul")


class InvestorFlowSource(Protocol):
    async def fetch_flows(self, target: InstrumentTarget, now: datetime) -> InvestorFlowBundle: ...

    async def close(self) -> None: ...


@final
class KisInvestorFlowAdapter:
    def __init__(self, client: KisHttpClient) -> None:
        self._client = client

    async def fetch_flows(self, target: InstrumentTarget, now: datetime) -> InvestorFlowBundle:
        raw = await self._client.get(
            endpoint=INVESTOR_FLOWS_ENDPOINT,
            transaction_id=_TRANSACTION_ID,
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": target.symbol},
            request_fingerprint=f"investor_flows:{target.symbol}",
        )
        response = parse_response(raw, KisInvestorResponse, BrokerOperation.INVESTOR_FLOWS)
        seoul_today = now.astimezone(_SEOUL).date()
        completed = [row for row in response.output if _row_date(row) < seoul_today]
        flows = tuple(
            _flow_from(target, row, raw.received_at) for row in completed if _has_amounts(row)
        )
        skipped = tuple(_row_date(row) for row in completed if not _has_amounts(row))
        return InvestorFlowBundle(
            target=target,
            flows=flows,
            raw=raw_from(BrokerOperation.INVESTOR_FLOWS, raw),
            collected_at=raw.received_at,
            skipped_blank_dates=skipped,
        )

    async def close(self) -> None:
        await self._client.close()


def _has_amounts(row: KisInvestorRow) -> bool:
    """투자자 필드가 비어 있으면 그 거래일은 값을 만들지 않는다.

    실측(2026-08-23, 한화 000880의 2026-08-21): 한 거래일의 투자자 필드가 전부 빈 문자열로 온다.
    0으로 채우면 "순매수가 0이었다"는 시장에 대한 주장이 된다. 한 행 때문에 종목 전체를 실패로
    돌리면 축적 설계에서 그 종목이 영구히 막힌다.
    """
    return all(
        value != ""
        for value in (
            row.prsn_ntby_qty,
            row.frgn_ntby_qty,
            row.orgn_ntby_qty,
            row.prsn_ntby_tr_pbmn,
            row.frgn_ntby_tr_pbmn,
            row.orgn_ntby_tr_pbmn,
        )
    )


def _row_date(row: KisInvestorRow) -> date:
    return datetime.strptime(row.stck_bsop_date, "%Y%m%d").replace(tzinfo=_SEOUL).date()


def _flow_from(
    target: InstrumentTarget,
    row: KisInvestorRow,
    received_at: datetime,
) -> InvestorFlow:
    return InvestorFlow(
        symbol=target.symbol,
        trading_date=_row_date(row),
        individual_net_quantity=int(row.prsn_ntby_qty),
        foreign_net_quantity=int(row.frgn_ntby_qty),
        institution_net_quantity=int(row.orgn_ntby_qty),
        individual_net_value=int(row.prsn_ntby_tr_pbmn),
        foreign_net_value=int(row.frgn_ntby_tr_pbmn),
        institution_net_value=int(row.orgn_ntby_tr_pbmn),
        source=KIS_SOURCE,
        received_at=received_at,
    )
