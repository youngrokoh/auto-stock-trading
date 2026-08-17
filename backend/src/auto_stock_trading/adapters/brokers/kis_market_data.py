from typing import TYPE_CHECKING, Protocol, final

from auto_stock_trading.adapters.brokers.kis_contracts import (
    KisDailyBarsResponse,
    KisInstrumentResponse,
    KisQuoteResponse,
)
from auto_stock_trading.adapters.brokers.kis_mapping import (
    bar_from,
    instrument_from,
    instrument_from_daily_summary,
    listed_shares_from,
    parse_response,
    quote_from,
    raw_from,
)
from auto_stock_trading.domain.market_data.models import (
    BrokerOperation,
    InstrumentTarget,
    MarketDataBundle,
)

if TYPE_CHECKING:
    from datetime import date

    from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient

INSTRUMENT_ENDPOINT = "/uapi/domestic-stock/v1/quotations/search-stock-info"
QUOTE_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-price"
DAILY_BARS_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"


class MarketDataSource(Protocol):
    async def fetch_bundle(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
    ) -> MarketDataBundle: ...

    async def close(self) -> None: ...


@final
class KisMarketDataAdapter:
    def __init__(
        self,
        client: KisHttpClient,
        *,
        instrument_details_available: bool,
    ) -> None:
        self._client = client
        self._instrument_details_available = instrument_details_available

    async def fetch_bundle(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
    ) -> MarketDataBundle:
        if start_date > end_date:
            msg = "start_date must not be after end_date"
            raise ValueError(msg)
        instrument_raw = (
            await self._client.get(
                endpoint=INSTRUMENT_ENDPOINT,
                transaction_id="CTPF1002R",
                params={"PRDT_TYPE_CD": "300", "PDNO": target.symbol},
                request_fingerprint=f"instrument:{target.symbol}",
            )
            if self._instrument_details_available
            else None
        )
        quote_raw = await self._client.get(
            endpoint=QUOTE_ENDPOINT,
            transaction_id="FHKST01010100",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": target.symbol},
            request_fingerprint=f"quote:{target.symbol}",
        )
        bars_raw = await self._client.get(
            endpoint=DAILY_BARS_ENDPOINT,
            transaction_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": target.symbol,
                "FID_INPUT_DATE_1": start_date.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "1",
            },
            request_fingerprint=f"daily_bars:{target.symbol}:{start_date}:{end_date}:original",
        )
        quote_response = parse_response(quote_raw, KisQuoteResponse, BrokerOperation.QUOTE)
        bars_response = parse_response(
            bars_raw,
            KisDailyBarsResponse,
            BrokerOperation.DAILY_BARS,
        )
        if instrument_raw is None:
            instrument = instrument_from_daily_summary(
                target,
                bars_response,
                bars_raw.received_at,
            )
            raw_responses = (
                raw_from(BrokerOperation.QUOTE, quote_raw),
                raw_from(BrokerOperation.DAILY_BARS, bars_raw),
            )
        else:
            instrument_response = parse_response(
                instrument_raw,
                KisInstrumentResponse,
                BrokerOperation.INSTRUMENT,
            )
            instrument = instrument_from(target, instrument_response, instrument_raw.received_at)
            raw_responses = (
                raw_from(BrokerOperation.INSTRUMENT, instrument_raw),
                raw_from(BrokerOperation.QUOTE, quote_raw),
                raw_from(BrokerOperation.DAILY_BARS, bars_raw),
            )
        quote = quote_from(target, quote_response, quote_raw.received_at)
        listed_shares = listed_shares_from(target, quote_response, quote_raw.received_at)
        bars = tuple(bar_from(target, item, bars_raw.received_at) for item in bars_response.output2)
        return MarketDataBundle(
            target=target,
            instrument=instrument,
            quote=quote,
            listed_shares=listed_shares,
            daily_bars=bars,
            raw_responses=raw_responses,
            collected_at=max(raw.received_at for raw in raw_responses),
        )

    async def close(self) -> None:
        await self._client.close()
