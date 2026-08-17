from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    ListedShareCountRow,
)
from auto_stock_trading.domain.market_data.listed_shares import VersionedListedShareCount

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from auto_stock_trading.domain.market_data.listed_shares import ListedShareCount


async def save_listed_share_count(
    session: AsyncSession,
    observation: ListedShareCount,
    instrument_id: UUID,
    raw_response_id: UUID,
) -> None:
    current = await session.scalar(
        select(ListedShareCountRow).where(
            ListedShareCountRow.instrument_id == instrument_id,
            ListedShareCountRow.source == observation.source,
            ListedShareCountRow.superseded_at.is_(None),
        )
    )
    if current is not None and current.share_count == observation.share_count:
        current.as_of = observation.as_of
        current.received_at = observation.received_at
        current.raw_response_id = raw_response_id
        return
    version = 1
    if current is not None:
        current.superseded_at = observation.received_at
        version = current.version + 1
        await session.flush()
    session.add(
        ListedShareCountRow(
            id=uuid4(),
            instrument_id=instrument_id,
            share_count=observation.share_count,
            source=observation.source,
            as_of=observation.as_of,
            received_at=observation.received_at,
            version=version,
            valid_from=observation.received_at,
            superseded_at=None,
            raw_response_id=raw_response_id,
        )
    )


async def read_listed_share_count(
    sessions: async_sessionmaker[AsyncSession],
    symbol: str,
) -> VersionedListedShareCount | None:
    async with sessions() as session:
        row = await session.scalar(
            select(ListedShareCountRow)
            .join(InstrumentRow, ListedShareCountRow.instrument_id == InstrumentRow.id)
            .where(
                InstrumentRow.symbol == symbol,
                ListedShareCountRow.superseded_at.is_(None),
            )
            .order_by(ListedShareCountRow.received_at.desc())
            .limit(1)
        )
    if row is None:
        return None
    return VersionedListedShareCount(
        symbol=symbol,
        share_count=row.share_count,
        source=row.source,
        as_of=row.as_of,
        received_at=row.received_at,
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
    )
