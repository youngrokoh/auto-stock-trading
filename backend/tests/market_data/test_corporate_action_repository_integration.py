from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auto_stock_trading.adapters.database.market_data_corporate_action_repository import (
    CorporateActionEvidence,
    CorporateActionRange,
    read_corporate_action_history,
    read_corporate_actions_as_of,
    read_current_corporate_actions,
    save_corporate_action,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    CorporateActionRow,
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    InvalidCorporateActionError,
    TimePrecision,
)
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    type Sessions = async_sessionmaker[AsyncSession]
    type CorporateActionScenario = Callable[[Sessions, UUID, UUID], Awaitable[None]]

_SYMBOL = "TESTCA"
_RECEIVED_AT = datetime(2026, 8, 16, 1, 0, tzinfo=UTC)


def test_same_source_event_replay_reuses_current_version() -> None:
    async def scenario(sessions: Sessions, instrument_id: UUID, raw_id: UUID) -> None:
        # Given
        evidence = _dividend_evidence(instrument_id, raw_id)
        await _save(sessions, evidence)
        replay_raw_id = await _add_raw_response(sessions)
        replayed = CorporateActionEvidence(
            action=replace(evidence.action, received_at=_RECEIVED_AT + timedelta(hours=1)),
            action_key=uuid4(),
            instrument_id=instrument_id,
            raw_response_id=replay_raw_id,
        )

        # When
        await _save(sessions, replayed)

        # Then
        rows = await _rows(sessions)
        assert len(rows) == 1
        assert rows[0].version == 1
        assert rows[0].action_key == evidence.action_key
        assert rows[0].received_at == _RECEIVED_AT + timedelta(hours=1)
        assert rows[0].raw_response_id == replay_raw_id
        assert rows[0].superseded_at is None

    anyio.run(_run_scenario, scenario)


def test_next_day_replay_of_same_source_event_reuses_current_version() -> None:
    async def scenario(sessions: Sessions, instrument_id: UUID, raw_id: UUID) -> None:
        # Given
        evidence = _dividend_evidence(instrument_id, raw_id)
        await _save(sessions, evidence)
        next_day = _RECEIVED_AT + timedelta(days=1)
        replayed = CorporateActionEvidence(
            action=replace(
                evidence.action,
                announcement_date=next_day.date(),
                available_at=next_day,
                received_at=next_day,
            ),
            action_key=uuid4(),
            instrument_id=instrument_id,
            raw_response_id=await _add_raw_response(sessions),
        )

        # When
        await _save(sessions, replayed)

        # Then
        rows = await _rows(sessions)
        assert len(rows) == 1
        assert rows[0].version == 1
        assert rows[0].announcement_date == evidence.action.announcement_date
        assert rows[0].available_at == evidence.action.available_at
        assert rows[0].received_at == next_day

    anyio.run(_run_scenario, scenario)


def test_correction_supersedes_previous_version_and_keeps_history() -> None:
    async def scenario(sessions: Sessions, instrument_id: UUID, raw_id: UUID) -> None:
        # Given
        evidence = _dividend_evidence(instrument_id, raw_id)
        await _save(sessions, evidence)
        corrected_at = _RECEIVED_AT + timedelta(hours=2)
        corrected = _corrected_evidence(evidence, corrected_at)

        # When
        await _save(sessions, corrected)

        # Then
        rows = await _rows(sessions)
        current = await read_current_corporate_actions(sessions, _full_range())
        history = await read_corporate_action_history(sessions, _full_range())
        assert tuple(row.version for row in rows) == (1, 2)
        assert rows[0].superseded_at == corrected_at
        assert rows[0].cash_amount == Decimal(361)
        assert rows[1].superseded_at is None
        assert rows[1].action_key == evidence.action_key
        assert len(current) == 1
        assert current[0].version == 2
        assert current[0].action.cash_amount == Decimal(400)
        assert tuple(item.version for item in history) == (1, 2)

    anyio.run(_run_scenario, scenario)


def test_cancellation_creates_new_version_without_deleting_history() -> None:
    async def scenario(sessions: Sessions, instrument_id: UUID, raw_id: UUID) -> None:
        # Given
        evidence = _dividend_evidence(instrument_id, raw_id)
        await _save(sessions, evidence)
        cancelled_at = _RECEIVED_AT + timedelta(hours=2)
        cancelled = CorporateActionEvidence(
            action=replace(
                evidence.action,
                lifecycle=CorporateActionLifecycle.CANCELLED,
                source_event_id="20260816000009",
                source_reference="https://dart.fss.or.kr/report/20260816000009",
                available_at=cancelled_at,
                received_at=cancelled_at,
            ),
            action_key=evidence.action_key,
            instrument_id=instrument_id,
            raw_response_id=await _add_raw_response(sessions),
        )

        # When
        await _save(sessions, cancelled)

        # Then
        rows = await _rows(sessions)
        assert tuple(row.version for row in rows) == (1, 2)
        assert rows[0].lifecycle_status == "announced"
        assert rows[0].superseded_at == cancelled_at
        assert rows[1].lifecycle_status == "cancelled"
        assert rows[1].superseded_at is None

    anyio.run(_run_scenario, scenario)


def test_stale_correction_is_rejected_without_new_version() -> None:
    async def scenario(sessions: Sessions, instrument_id: UUID, raw_id: UUID) -> None:
        # Given
        evidence = _dividend_evidence(instrument_id, raw_id)
        await _save(sessions, evidence)
        stale = _corrected_evidence(evidence, _RECEIVED_AT - timedelta(hours=1))

        # When
        with pytest.raises(InvalidCorporateActionError):
            await _save(sessions, stale)

        # Then
        rows = await _rows(sessions)
        assert len(rows) == 1
        assert rows[0].version == 1
        assert rows[0].superseded_at is None

    anyio.run(_run_scenario, scenario)


def test_point_in_time_read_selects_version_known_at_cutoff() -> None:
    async def scenario(sessions: Sessions, instrument_id: UUID, raw_id: UUID) -> None:
        # Given
        evidence = _dividend_evidence(instrument_id, raw_id)
        await _save(sessions, evidence)
        corrected_available_at = _RECEIVED_AT + timedelta(days=1)
        await _save(sessions, _corrected_evidence(evidence, corrected_available_at))

        # When
        before_correction = await read_corporate_actions_as_of(
            sessions,
            _full_range(),
            knowledge_cutoff_at=corrected_available_at - timedelta(hours=1),
        )
        after_correction = await read_corporate_actions_as_of(
            sessions,
            _full_range(),
            knowledge_cutoff_at=corrected_available_at,
        )
        before_announcement = await read_corporate_actions_as_of(
            sessions,
            _full_range(),
            knowledge_cutoff_at=evidence.action.available_at - timedelta(days=1),
        )

        # Then
        assert len(before_correction) == 1
        assert before_correction[0].version == 1
        assert before_correction[0].action.cash_amount == Decimal(361)
        assert len(after_correction) == 1
        assert after_correction[0].version == 2
        assert after_correction[0].action.cash_amount == Decimal(400)
        assert before_announcement == ()

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: CorporateActionScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            instrument_id, raw_id = await _add_instrument_and_raw_response(sessions)
            await scenario(sessions, instrument_id, raw_id)
        finally:
            await transaction.rollback()
    await engine.dispose()


async def _save(sessions: Sessions, evidence: CorporateActionEvidence) -> None:
    async with sessions.begin() as session:
        await save_corporate_action(session, evidence)


def _dividend_evidence(instrument_id: UUID, raw_response_id: UUID) -> CorporateActionEvidence:
    return CorporateActionEvidence(
        action=CorporateAction(
            action_type=CorporateActionType.CASH_DIVIDEND,
            lifecycle=CorporateActionLifecycle.ANNOUNCED,
            quality=CorporateActionQuality.PENDING,
            announced_at=None,
            announcement_date=date(2026, 8, 14),
            time_precision=TimePrecision.DATE,
            ex_date=date(2026, 9, 25),
            effective_date=None,
            record_date=date(2026, 9, 30),
            payment_date=None,
            share_multiplier=None,
            cash_amount=Decimal(361),
            currency="KRW",
            subscription_price=None,
            related_instrument_id=None,
            source="DART",
            source_event_id="20260814000001",
            source_reference="https://dart.fss.or.kr/report/20260814000001",
            available_at=datetime(2026, 8, 14, 7, 30, tzinfo=UTC),
            received_at=_RECEIVED_AT,
        ),
        action_key=uuid4(),
        instrument_id=instrument_id,
        raw_response_id=raw_response_id,
    )


def _corrected_evidence(
    evidence: CorporateActionEvidence,
    corrected_at: datetime,
) -> CorporateActionEvidence:
    return CorporateActionEvidence(
        action=replace(
            evidence.action,
            cash_amount=Decimal(400),
            source_event_id="20260816000002",
            source_reference="https://dart.fss.or.kr/report/20260816000002",
            available_at=corrected_at,
            received_at=corrected_at,
        ),
        action_key=evidence.action_key,
        instrument_id=evidence.instrument_id,
        raw_response_id=evidence.raw_response_id,
    )


def _full_range() -> CorporateActionRange:
    return CorporateActionRange(_SYMBOL, date(2026, 9, 1), date(2026, 9, 30))


async def _add_instrument_and_raw_response(sessions: Sessions) -> tuple[UUID, UUID]:
    instrument_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            InstrumentRow(
                id=instrument_id,
                country="KR",
                exchange="XKRX",
                symbol=_SYMBOL,
                product_type="stock",
                currency="KRW",
                name="기업행사 검증 종목",
                english_name=None,
                listed_on=None,
                delisted_on=None,
                trading_status="trading",
                source="KIS",
                source_as_of=date(2026, 8, 16),
                created_at=_RECEIVED_AT,
                updated_at=_RECEIVED_AT,
            )
        )
    return instrument_id, await _add_raw_response(sessions)


async def _add_raw_response(sessions: Sessions) -> UUID:
    raw_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            RawApiResponseRow(
                id=raw_id,
                source="DART",
                operation="corporate_actions",
                endpoint="https://opendart.fss.or.kr/api/list.json",
                request_fingerprint=f"test-{raw_id}",
                received_at=_RECEIVED_AT,
                payload_json="{}",
            )
        )
    return raw_id


async def _rows(sessions: Sessions) -> tuple[CorporateActionRow, ...]:
    async with sessions() as session:
        return tuple(
            (
                await session.scalars(
                    select(CorporateActionRow)
                    .join(InstrumentRow, CorporateActionRow.instrument_id == InstrumentRow.id)
                    .where(InstrumentRow.symbol == _SYMBOL)
                    .order_by(CorporateActionRow.version)
                )
            ).all()
        )
