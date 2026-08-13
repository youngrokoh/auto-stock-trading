from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status

from auto_stock_trading.api.market_data_models import (
    DailyBarResponse,
    DailyBarsResponse,
    InstrumentResponse,
    QuoteResponse,
)

if TYPE_CHECKING:
    from auto_stock_trading.application.market_data import MarketDataReader


def create_market_data_router(reader: MarketDataReader) -> APIRouter:
    router = APIRouter(prefix="/api/market-data/instruments", tags=["market-data"])

    async def instrument(symbol: str) -> InstrumentResponse:
        result = await reader.instrument(symbol)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")
        return InstrumentResponse(
            country=result.country,
            exchange=result.exchange,
            symbol=result.symbol,
            product_type=result.product_type,
            currency=result.currency,
            name=result.name,
            english_name=result.english_name,
            listed_on=result.listed_on,
            delisted_on=result.delisted_on,
            trading_status=result.trading_status,
            source=result.source,
            source_as_of=result.source_as_of,
        )

    async def quote(symbol: str) -> QuoteResponse:
        result = await reader.quote(symbol)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quote not found")
        return QuoteResponse(
            symbol=result.symbol,
            price=result.price,
            open_price=result.open_price,
            high_price=result.high_price,
            low_price=result.low_price,
            previous_close=result.previous_close,
            change=result.change,
            change_percent=result.change_percent,
            volume=result.volume,
            trading_value=result.trading_value,
            currency=result.currency,
            source=result.source,
            as_of=result.as_of,
            received_at=result.received_at,
        )

    async def daily_bars(
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DailyBarsResponse:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "start_date must not be after end_date",
            )
        results = await reader.daily_bars(symbol, start_date, end_date)
        if not results and await reader.instrument(symbol) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")
        bars = tuple(
            DailyBarResponse(
                trading_date=result.trading_date,
                open_price=result.open_price,
                high_price=result.high_price,
                low_price=result.low_price,
                close_price=result.close_price,
                volume=result.volume,
                trading_value=result.trading_value,
                adjusted=result.adjusted,
                correction_code=result.correction_code,
                split_ratio=result.split_ratio,
                source=result.source,
                received_at=result.received_at,
            )
            for result in results
        )
        return DailyBarsResponse(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            source=results[0].source if results else None,
            bars=bars,
        )

    router.add_api_route("/{symbol}", instrument, methods=["GET"])
    router.add_api_route("/{symbol}/quote", quote, methods=["GET"])
    router.add_api_route("/{symbol}/daily-bars", daily_bars, methods=["GET"])
    return router
