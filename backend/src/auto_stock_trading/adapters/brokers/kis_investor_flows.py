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
        flows = tuple(
            _flow_from(target, row, raw.received_at)
            for row in response.output
            if _row_date(row) < seoul_today
        )
        return InvestorFlowBundle(
            target=target,
            flows=flows,
            raw=raw_from(BrokerOperation.INVESTOR_FLOWS, raw),
            collected_at=raw.received_at,
        )

    async def close(self) -> None:
        await self._client.close()


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
