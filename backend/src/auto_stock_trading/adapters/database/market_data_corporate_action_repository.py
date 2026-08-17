from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Select, func, select

from auto_stock_trading.adapters.database.market_data_rows import (
    CorporateActionRow,
    InstrumentRow,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionInvariant,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    InvalidCorporateActionError,
    TimePrecision,
    VersionedCorporateAction,
    validate_corporate_action,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class CorporateActionEvidence:
    action: CorporateAction
    action_key: UUID
    instrument_id: UUID
    raw_response_id: UUID


@dataclass(frozen=True, slots=True)
class CorporateActionRange:
    symbol: str
    start_date: date | None
    end_date: date | None


async def save_corporate_action(session: AsyncSession, evidence: CorporateActionEvidence) -> None:
    action = evidence.action
    validate_corporate_action(action)
    matched = await session.scalar(
        select(CorporateActionRow)
        .where(
            CorporateActionRow.source == action.source,
            CorporateActionRow.source_event_id == action.source_event_id,
        )
        .order_by(CorporateActionRow.version.desc())
        .limit(1)
        .with_for_update()
    )
    if matched is not None and _corporate_action_facts_match(matched, action):
        if matched.superseded_at is None and action.received_at > matched.received_at:
            matched.received_at = action.received_at
            matched.raw_response_id = evidence.raw_response_id
        return
    action_key = evidence.action_key if matched is None else matched.action_key
    current = await session.scalar(
        select(CorporateActionRow)
        .where(
            CorporateActionRow.action_key == action_key,
            CorporateActionRow.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current is None:
        session.add(_new_corporate_action_row(evidence, action_key, 1))
        return
    if action.received_at <= current.received_at:
        raise InvalidCorporateActionError(CorporateActionInvariant.VALIDITY)
    current.superseded_at = action.received_at
    session.add(_new_corporate_action_row(evidence, action_key, current.version + 1))


async def read_current_corporate_actions(
    sessions: async_sessionmaker[AsyncSession],
    query: CorporateActionRange,
) -> tuple[VersionedCorporateAction, ...]:
    statement = _range_statement(query).where(CorporateActionRow.superseded_at.is_(None))
    return await _read(sessions, statement)


async def read_corporate_action_history(
    sessions: async_sessionmaker[AsyncSession],
    query: CorporateActionRange,
) -> tuple[VersionedCorporateAction, ...]:
    return await _read(sessions, _range_statement(query))


async def read_corporate_actions_as_of(
    sessions: async_sessionmaker[AsyncSession],
    query: CorporateActionRange,
    knowledge_cutoff_at: datetime,
) -> tuple[VersionedCorporateAction, ...]:
    known = (
        select(
            CorporateActionRow.action_key.label("action_key"),
            func.max(CorporateActionRow.version).label("version"),
        )
        .where(CorporateActionRow.available_at <= knowledge_cutoff_at)
        .group_by(CorporateActionRow.action_key)
        .subquery()
    )
    statement = _range_statement(query).join(
        known,
        (CorporateActionRow.action_key == known.c.action_key)
        & (CorporateActionRow.version == known.c.version),
    )
    return await _read(sessions, statement)


def _range_statement(query: CorporateActionRange) -> Select[tuple[CorporateActionRow]]:
    event_date = func.coalesce(CorporateActionRow.ex_date, CorporateActionRow.effective_date)
    statement = (
        select(CorporateActionRow)
        .join(InstrumentRow, CorporateActionRow.instrument_id == InstrumentRow.id)
        .where(InstrumentRow.symbol == query.symbol)
    )
    if query.start_date is not None:
        statement = statement.where(event_date >= query.start_date)
    if query.end_date is not None:
        statement = statement.where(event_date <= query.end_date)
    return statement.order_by(
        event_date,
        CorporateActionRow.action_key,
        CorporateActionRow.version,
    )


async def _read(
    sessions: async_sessionmaker[AsyncSession],
    statement: Select[tuple[CorporateActionRow]],
) -> tuple[VersionedCorporateAction, ...]:
    async with sessions() as session:
        rows = tuple((await session.scalars(statement)).all())
    return tuple(_versioned_corporate_action(row) for row in rows)


def _new_corporate_action_row(
    evidence: CorporateActionEvidence,
    action_key: UUID,
    version: int,
) -> CorporateActionRow:
    action = evidence.action
    return CorporateActionRow(
        id=uuid4(),
        action_key=action_key,
        instrument_id=evidence.instrument_id,
        action_type=action.action_type.value,
        lifecycle_status=action.lifecycle.value,
        quality_state=action.quality.value,
        announced_at=action.announced_at,
        announcement_date=action.announcement_date,
        time_precision=action.time_precision.value,
        ex_date=action.ex_date,
        effective_date=action.effective_date,
        record_date=action.record_date,
        payment_date=action.payment_date,
        share_multiplier=action.share_multiplier,
        cash_amount=action.cash_amount,
        currency=action.currency,
        subscription_price=action.subscription_price,
        related_instrument_id=action.related_instrument_id,
        source=action.source,
        source_event_id=action.source_event_id,
        source_reference=action.source_reference,
        available_at=action.available_at,
        received_at=action.received_at,
        version=version,
        valid_from=action.received_at,
        superseded_at=None,
        raw_response_id=evidence.raw_response_id,
    )


def _corporate_action_facts_match(row: CorporateActionRow, action: CorporateAction) -> bool:
    return (
        row.action_type == action.action_type.value
        and row.lifecycle_status == action.lifecycle.value
        and row.quality_state == action.quality.value
        and row.announced_at == action.announced_at
        and row.time_precision == action.time_precision.value
        and row.ex_date == action.ex_date
        and row.effective_date == action.effective_date
        and row.record_date == action.record_date
        and row.payment_date == action.payment_date
        and row.share_multiplier == action.share_multiplier
        and row.cash_amount == action.cash_amount
        and row.currency == action.currency
        and row.subscription_price == action.subscription_price
        and row.related_instrument_id == action.related_instrument_id
        and row.source_reference == action.source_reference
    )


def _versioned_corporate_action(row: CorporateActionRow) -> VersionedCorporateAction:
    return VersionedCorporateAction(
        action=CorporateAction(
            action_type=CorporateActionType(row.action_type),
            lifecycle=CorporateActionLifecycle(row.lifecycle_status),
            quality=CorporateActionQuality(row.quality_state),
            announced_at=row.announced_at,
            announcement_date=row.announcement_date,
            time_precision=TimePrecision(row.time_precision),
            ex_date=row.ex_date,
            effective_date=row.effective_date,
            record_date=row.record_date,
            payment_date=row.payment_date,
            share_multiplier=row.share_multiplier,
            cash_amount=row.cash_amount,
            currency=row.currency,
            subscription_price=row.subscription_price,
            related_instrument_id=row.related_instrument_id,
            source=row.source,
            source_event_id=row.source_event_id,
            source_reference=row.source_reference,
            available_at=row.available_at,
            received_at=row.received_at,
        ),
        action_key=row.action_key,
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
    )
