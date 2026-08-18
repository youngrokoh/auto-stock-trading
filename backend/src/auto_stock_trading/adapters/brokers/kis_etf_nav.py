from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from zoneinfo import ZoneInfo

from auto_stock_trading.adapters.brokers.kis_contracts import KisEtfPriceResponse
from auto_stock_trading.adapters.brokers.kis_mapping import (
    KIS_SOURCE,
    parse_response,
    raw_from,
)
from auto_stock_trading.domain.market_data.etf import EtfNavObservation, EtfNavSnapshot
from auto_stock_trading.domain.market_data.models import BrokerOperation

if TYPE_CHECKING:
    from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient

ETF_PRICE_ENDPOINT = "/uapi/etfetn/v1/quotations/inquire-price"
_TRANSACTION_ID: Final = "FHPST02400000"
_SEOUL: Final = ZoneInfo("Asia/Seoul")
_DATE_LENGTH: Final = 8


@final
class KisEtfNavAdapter:
    def __init__(self, client: KisHttpClient) -> None:
        self._client = client

    async def fetch_snapshot(self, symbol: str) -> EtfNavObservation:
        raw = await self._client.get(
            endpoint=ETF_PRICE_ENDPOINT,
            transaction_id=_TRANSACTION_ID,
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
            request_fingerprint=f"etf_nav:{symbol}",
        )
        response = parse_response(raw, KisEtfPriceResponse, BrokerOperation.ETF_NAV)
        output = response.output
        snapshot = EtfNavSnapshot(
            symbol=symbol,
            price=_decimal(output.stck_prpr),
            change_percent=_decimal(output.prdy_ctrt),
            volume=int(output.acml_vol),
            previous_volume=int(output.prdy_vol),
            nav=_decimal(output.nav),
            divergence_rate=_decimal(output.dprt),
            tracking_error=_decimal(output.trc_errt),
            tracking_multiple=_decimal(output.etf_trc_ert_mltp),
            net_asset_total=int(output.etf_ntas_ttam),
            listed_shares=int(output.lstn_stcn),
            manager=output.mbcr_name,
            index_name=output.etf_rprs_bstp_kor_isnm,
            listing_date=_listing_date(output.stck_lstn_date),
            currency=output.crcd,
            source=KIS_SOURCE,
            as_of=raw.received_at,
            received_at=raw.received_at,
        )
        return EtfNavObservation(snapshot=snapshot, raw=raw_from(BrokerOperation.ETF_NAV, raw))

    async def close(self) -> None:
        await self._client.close()


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def _listing_date(value: str) -> date | None:
    if len(value) != _DATE_LENGTH or not value.isdigit():
        return None
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=_SEOUL).date()
