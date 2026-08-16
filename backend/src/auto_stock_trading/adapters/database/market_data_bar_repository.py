from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Select, select

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow, MarketBarRow
from auto_stock_trading.domain.market_data.models import (
    BarFinality,
    DailyBar,
    InvalidMarketBarError,
    MarketBarInvariant,
    VersionedDailyBar,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class MarketBarEvidence:
    bar: DailyBar
    instrument_id: UUID
    raw_response_id: UUID


@dataclass(frozen=True, slots=True)
class MarketBarRange:
    symbol: str
    start_date: date | None
    end_date: date | None


async def save_market_bar(session: AsyncSession, evidence: MarketBarEvidence) -> None:
    bar = evidence.bar
    if bar.adjusted:
        raise InvalidMarketBarError(MarketBarInvariant.UNADJUSTED)
    current = await session.scalar(
        _current_bar_statement(evidence.instrument_id, bar).with_for_update()
    )
    if current is None:
        session.add(_new_market_bar_row(evidence, 1))
        return
    if _market_bar_facts_match(current, bar):
        if bar.received_at > current.received_at:
            current.received_at = bar.received_at
            current.raw_response_id = evidence.raw_response_id
        return
    if bar.received_at <= current.received_at:
        raise InvalidMarketBarError(MarketBarInvariant.VALIDITY)
    current.superseded_at = bar.received_at
    session.add(_new_market_bar_row(evidence, current.version + 1))


async def confirm_market_bar(
    session: AsyncSession,
    bar: DailyBar,
    confirmed_at: datetime,
) -> bool:
    instrument_id = await session.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == bar.symbol).limit(1)
    )
    if instrument_id is None:
        return False
    current = await session.scalar(_current_bar_statement(instrument_id, bar).with_for_update())
    if current is None or not _market_bar_facts_match(current, bar):
        return False
    if current.finality == BarFinality.PENDING.value:
        current.finality = BarFinality.CONFIRMED.value
        current.confirmed_at = confirmed_at
    return True


async def read_market_bars(
    sessions: async_sessionmaker[AsyncSession],
    query: MarketBarRange,
) -> tuple[VersionedDailyBar, ...]:
    statement = (
        select(MarketBarRow)
        .join(InstrumentRow, MarketBarRow.instrument_id == InstrumentRow.id)
        .where(
            InstrumentRow.symbol == query.symbol,
            MarketBarRow.superseded_at.is_(None),
        )
    )
    if query.start_date is not None:
        statement = statement.where(MarketBarRow.trading_date >= query.start_date)
    if query.end_date is not None:
        statement = statement.where(MarketBarRow.trading_date <= query.end_date)
    async with sessions() as session:
        rows = tuple((await session.scalars(statement.order_by(MarketBarRow.trading_date))).all())
    return tuple(_versioned_daily_bar(query.symbol, row) for row in rows)


def _current_bar_statement(
    instrument_id: UUID,
    bar: DailyBar,
) -> Select[tuple[MarketBarRow]]:
    return select(MarketBarRow).where(
        MarketBarRow.instrument_id == instrument_id,
        MarketBarRow.interval == "1d",
        MarketBarRow.trading_date == bar.trading_date,
        MarketBarRow.source == bar.source,
        MarketBarRow.superseded_at.is_(None),
    )


def _new_market_bar_row(evidence: MarketBarEvidence, version: int) -> MarketBarRow:
    bar = evidence.bar
    return MarketBarRow(
        id=uuid4(),
        instrument_id=evidence.instrument_id,
        interval="1d",
        trading_date=bar.trading_date,
        open_price=bar.open_price,
        high_price=bar.high_price,
        low_price=bar.low_price,
        close_price=bar.close_price,
        volume=bar.volume,
        trading_value=bar.trading_value,
        adjusted=bar.adjusted,
        correction_code=bar.correction_code,
        split_ratio=bar.split_ratio,
        source=bar.source,
        received_at=bar.received_at,
        finality=BarFinality.PENDING.value,
        confirmed_at=None,
        version=version,
        valid_from=bar.received_at,
        superseded_at=None,
        raw_response_id=evidence.raw_response_id,
    )


def _market_bar_facts_match(row: MarketBarRow, bar: DailyBar) -> bool:
    return (
        row.open_price == bar.open_price
        and row.high_price == bar.high_price
        and row.low_price == bar.low_price
        and row.close_price == bar.close_price
        and row.volume == bar.volume
        and row.trading_value == bar.trading_value
        and row.adjusted == bar.adjusted
        and row.correction_code == bar.correction_code
        and row.split_ratio == bar.split_ratio
    )


def _versioned_daily_bar(symbol: str, row: MarketBarRow) -> VersionedDailyBar:
    return VersionedDailyBar(
        bar=DailyBar(
            symbol=symbol,
            trading_date=row.trading_date,
            open_price=row.open_price,
            high_price=row.high_price,
            low_price=row.low_price,
            close_price=row.close_price,
            volume=row.volume,
            trading_value=row.trading_value,
            adjusted=row.adjusted,
            correction_code=row.correction_code,
            split_ratio=row.split_ratio,
            source=row.source,
            received_at=row.received_at,
        ),
        finality=BarFinality(row.finality),
        confirmed_at=row.confirmed_at,
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
    )
