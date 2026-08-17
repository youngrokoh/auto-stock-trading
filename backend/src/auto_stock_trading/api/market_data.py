from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status

from auto_stock_trading.api.market_data_models import (
    DailyBarResponse,
    DailyBarsResponse,
    InstrumentResponse,
    InstrumentsResponse,
    MinuteBarResponse,
    MinuteBarsResponse,
    QuoteResponse,
)

if TYPE_CHECKING:
    from auto_stock_trading.application.market_data import MarketDataReader
    from auto_stock_trading.domain.market_data.models import Instrument


def create_market_data_router(reader: MarketDataReader) -> APIRouter:
    router = APIRouter(prefix="/api/market-data/instruments", tags=["market-data"])

    async def instrument_list() -> InstrumentsResponse:
        results = await reader.instruments()
        return InstrumentsResponse(
            instruments=tuple(_instrument_response(result) for result in results)
        )

    async def instrument(symbol: str) -> InstrumentResponse:
        result = await reader.instrument(symbol)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")
        return _instrument_response(result)

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
        await _ensure_known_instrument(reader, symbol, has_results=bool(results))
        bars = tuple(
            DailyBarResponse(
                trading_date=result.bar.trading_date,
                open_price=result.bar.open_price,
                high_price=result.bar.high_price,
                low_price=result.bar.low_price,
                close_price=result.bar.close_price,
                volume=result.bar.volume,
                trading_value=result.bar.trading_value,
                adjusted=result.bar.adjusted,
                correction_code=result.bar.correction_code,
                split_ratio=result.bar.split_ratio,
                source=result.bar.source,
                received_at=result.bar.received_at,
                finality=result.finality.value,
                confirmed_at=result.confirmed_at,
                version=result.version,
                valid_from=result.valid_from,
            )
            for result in results
        )
        return DailyBarsResponse(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            source=results[0].bar.source if results else None,
            bars=bars,
        )

    async def minute_bars(symbol: str, trading_date: date) -> MinuteBarsResponse:
        results = await reader.minute_bars(symbol, trading_date)
        await _ensure_known_instrument(reader, symbol, has_results=bool(results))
        bars = tuple(
            MinuteBarResponse(
                bar_started_at=result.bar.bar_started_at,
                open_price=result.bar.open_price,
                high_price=result.bar.high_price,
                low_price=result.bar.low_price,
                close_price=result.bar.close_price,
                volume=result.bar.volume,
                cumulative_trading_value=result.bar.cumulative_trading_value,
                source=result.bar.source,
                received_at=result.bar.received_at,
                finality=result.finality.value,
                confirmed_at=result.confirmed_at,
                version=result.version,
                valid_from=result.valid_from,
            )
            for result in results
        )
        return MinuteBarsResponse(
            symbol=symbol,
            trading_date=trading_date,
            source=results[0].bar.source if results else None,
            bars=bars,
        )

    router.add_api_route(
        "",
        instrument_list,
        methods=["GET"],
        description="수집 대상으로 등록된 종목 목록을 종목코드 순으로 반환한다.",
    )
    router.add_api_route("/{symbol}", instrument, methods=["GET"])
    router.add_api_route("/{symbol}/quote", quote, methods=["GET"])
    router.add_api_route("/{symbol}/daily-bars", daily_bars, methods=["GET"])
    router.add_api_route(
        "/{symbol}/minute-bars",
        minute_bars,
        methods=["GET"],
        description=(
            "검증된 시장 달력 세션 창 안의 비수정 1분봉 현재 버전을 반환한다. "
            "`pending`은 재관측 확정 전 값이며 전략 입력에 사용할 수 없다. "
            "`cumulative_trading_value`는 원본이 제공하는 당일 누적 거래대금이다."
        ),
    )
    return router


async def _ensure_known_instrument(
    reader: MarketDataReader,
    symbol: str,
    *,
    has_results: bool,
) -> None:
    if not has_results and await reader.instrument(symbol) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")


def _instrument_response(result: Instrument) -> InstrumentResponse:
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
