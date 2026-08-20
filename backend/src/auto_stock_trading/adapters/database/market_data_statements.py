from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy.dialects.postgresql import Insert, insert

from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    QuoteRow,
    SyncStatusRow,
)
from auto_stock_trading.domain.market_data.models import (
    BrokerOperation,
    ProductType,
    SyncState,
)

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.models import MarketDataBundle, Quote


def instrument_id_for(
    *,
    country: str,
    exchange: str,
    symbol: str,
    product_type: ProductType,
    currency: str,
) -> UUID:
    """종목 식별자는 정체성에서 결정적으로 나온다. 행을 읽지 않고 참조를 만들 수 있다."""
    identity = f"{country}:{exchange}:{symbol}:{product_type.value}:{currency}"
    return uuid5(NAMESPACE_URL, f"auto-stock-trading:instrument:{identity}")


def instrument_identifier(bundle: MarketDataBundle) -> UUID:
    instrument = bundle.instrument
    return instrument_id_for(
        country=instrument.country,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        product_type=instrument.product_type,
        currency=instrument.currency,
    )


def instrument_upsert(
    bundle: MarketDataBundle,
    instrument_id: UUID,
    now: datetime,
) -> Insert:
    instrument = bundle.instrument
    statement = insert(InstrumentRow).values(
        id=instrument_id,
        country=instrument.country,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        product_type=instrument.product_type.value,
        currency=instrument.currency,
        name=instrument.name,
        english_name=instrument.english_name,
        listed_on=instrument.listed_on,
        delisted_on=instrument.delisted_on,
        trading_status=instrument.trading_status,
        source=instrument.source,
        source_as_of=instrument.source_as_of,
        created_at=now,
        updated_at=now,
    )
    return statement.on_conflict_do_update(
        constraint="uq_instrument_identity",
        set_={
            "name": instrument.name,
            "english_name": instrument.english_name,
            "listed_on": instrument.listed_on,
            "delisted_on": instrument.delisted_on,
            "trading_status": instrument.trading_status,
            "source": instrument.source,
            "source_as_of": instrument.source_as_of,
            "updated_at": now,
        },
    )


def quote_upsert(
    bundle: MarketDataBundle,
    instrument_id: UUID,
    raw_ids: dict[BrokerOperation, UUID],
) -> Insert:
    return quote_snapshot_upsert(
        bundle.quote,
        instrument_id,
        raw_ids[BrokerOperation.QUOTE],
    )


def quote_snapshot_upsert(
    quote: Quote,
    instrument_id: UUID,
    raw_response_id: UUID,
) -> Insert:
    values = {
        "price": quote.price,
        "open_price": quote.open_price,
        "high_price": quote.high_price,
        "low_price": quote.low_price,
        "previous_close": quote.previous_close,
        "change": quote.change,
        "change_percent": quote.change_percent,
        "volume": quote.volume,
        "trading_value": quote.trading_value,
        "currency": quote.currency,
        "as_of": quote.as_of,
        "received_at": quote.received_at,
        "raw_response_id": raw_response_id,
    }
    statement = insert(QuoteRow).values(
        id=uuid4(), instrument_id=instrument_id, source=quote.source, **values
    )
    return statement.on_conflict_do_update(
        constraint="uq_quote_latest_source",
        set_=values,
    )


def success_upsert(bundle: MarketDataBundle) -> Insert:
    now = bundle.collected_at.astimezone(UTC)
    statement = insert(SyncStatusRow).values(
        id=uuid4(),
        source="KIS",
        operation="market_data_bundle",
        symbol=bundle.target.symbol,
        state=SyncState.SUCCESS.value,
        started_at=now,
        completed_at=now,
        last_success_at=now,
        error_code=None,
        error_message=None,
    )
    return statement.on_conflict_do_update(
        constraint="uq_sync_target",
        set_={
            "state": SyncState.SUCCESS.value,
            "completed_at": now,
            "last_success_at": now,
            "error_code": None,
            "error_message": None,
        },
    )
