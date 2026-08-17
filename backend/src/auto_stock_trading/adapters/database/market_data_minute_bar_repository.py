from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Select, select

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow, MinuteBarRow
from auto_stock_trading.domain.market_data.minute_bars import (
    InvalidMinuteBarError,
    MinuteBar,
    MinuteBarInvariant,
    VersionedMinuteBar,
)
from auto_stock_trading.domain.market_data.models import BarFinality

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_INTERVAL = "1m"


@dataclass(frozen=True, slots=True)
class MinuteBarEvidence:
    bar: MinuteBar
    instrument_id: UUID
    raw_response_id: UUID


async def save_minute_bar(session: AsyncSession, evidence: MinuteBarEvidence) -> None:
    bar = evidence.bar
    current = await session.scalar(
        _current_bar_statement(evidence.instrument_id, bar).with_for_update()
    )
    if current is None:
        session.add(_new_minute_bar_row(evidence, 1))
        return
    if _minute_bar_facts_match(current, bar):
        if bar.received_at > current.received_at:
            current.received_at = bar.received_at
            current.raw_response_id = evidence.raw_response_id
        return
    if bar.received_at <= current.received_at:
        raise InvalidMinuteBarError(MinuteBarInvariant.VALIDITY)
    current.superseded_at = bar.received_at
    session.add(_new_minute_bar_row(evidence, current.version + 1))


async def confirm_minute_bar(
    session: AsyncSession,
    bar: MinuteBar,
    confirmed_at: datetime,
) -> bool:
    instrument_id = await session.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == bar.symbol).limit(1)
    )
    if instrument_id is None:
        return False
    current = await session.scalar(_current_bar_statement(instrument_id, bar).with_for_update())
    if current is None or not _minute_bar_facts_match(current, bar):
        return False
    if current.finality == BarFinality.PENDING.value:
        current.finality = BarFinality.CONFIRMED.value
        current.confirmed_at = confirmed_at
    return True


async def read_minute_bars(
    sessions: async_sessionmaker[AsyncSession],
    symbol: str,
    trading_date: date,
) -> tuple[VersionedMinuteBar, ...]:
    statement = (
        select(MinuteBarRow)
        .join(InstrumentRow, MinuteBarRow.instrument_id == InstrumentRow.id)
        .where(
            InstrumentRow.symbol == symbol,
            MinuteBarRow.trading_date == trading_date,
            MinuteBarRow.superseded_at.is_(None),
        )
        .order_by(MinuteBarRow.bar_started_at)
    )
    async with sessions() as session:
        rows = tuple((await session.scalars(statement)).all())
    return tuple(_versioned_minute_bar(symbol, row) for row in rows)


def _current_bar_statement(
    instrument_id: UUID,
    bar: MinuteBar,
) -> Select[tuple[MinuteBarRow]]:
    return select(MinuteBarRow).where(
        MinuteBarRow.instrument_id == instrument_id,
        MinuteBarRow.interval == _INTERVAL,
        MinuteBarRow.bar_started_at == bar.bar_started_at,
        MinuteBarRow.source == bar.source,
        MinuteBarRow.superseded_at.is_(None),
    )


def _new_minute_bar_row(evidence: MinuteBarEvidence, version: int) -> MinuteBarRow:
    bar = evidence.bar
    return MinuteBarRow(
        id=uuid4(),
        instrument_id=evidence.instrument_id,
        interval=_INTERVAL,
        trading_date=bar.trading_date,
        bar_started_at=bar.bar_started_at,
        open_price=bar.open_price,
        high_price=bar.high_price,
        low_price=bar.low_price,
        close_price=bar.close_price,
        volume=bar.volume,
        cumulative_trading_value=bar.cumulative_trading_value,
        source=bar.source,
        received_at=bar.received_at,
        finality=BarFinality.PENDING.value,
        confirmed_at=None,
        version=version,
        valid_from=bar.received_at,
        superseded_at=None,
        raw_response_id=evidence.raw_response_id,
    )


def _minute_bar_facts_match(row: MinuteBarRow, bar: MinuteBar) -> bool:
    return (
        row.open_price == bar.open_price
        and row.high_price == bar.high_price
        and row.low_price == bar.low_price
        and row.close_price == bar.close_price
        and row.volume == bar.volume
        and row.cumulative_trading_value == bar.cumulative_trading_value
    )


def _versioned_minute_bar(symbol: str, row: MinuteBarRow) -> VersionedMinuteBar:
    return VersionedMinuteBar(
        bar=MinuteBar(
            symbol=symbol,
            trading_date=row.trading_date,
            bar_started_at=row.bar_started_at,
            open_price=row.open_price,
            high_price=row.high_price,
            low_price=row.low_price,
            close_price=row.close_price,
            volume=row.volume,
            cumulative_trading_value=row.cumulative_trading_value,
            source=row.source,
            received_at=row.received_at,
        ),
        finality=BarFinality(row.finality),
        confirmed_at=row.confirmed_at,
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
    )
