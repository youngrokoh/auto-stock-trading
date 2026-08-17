from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auto_stock_trading.adapters.database.fundamental_rows import (
    FinancialReportRow,
    FinancialStatementLineRow,
)
from auto_stock_trading.adapters.database.fundamental_statement_reader import (
    PostgresFinancialReportReader,
)
from auto_stock_trading.adapters.database.fundamental_statement_store import (
    PostgresFinancialReportStore,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    RawApiResponseRow,
    SyncStatusRow,
)
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialRawResponse,
    FinancialReport,
    FinancialReportObservation,
    FinancialStatementLine,
    FsDivision,
    InvalidFinancialReportError,
    ReportCode,
    StatementDivision,
)
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    type Sessions = async_sessionmaker[AsyncSession]
    type StoreScenario = Callable[
        [PostgresFinancialReportStore, PostgresFinancialReportReader, Sessions],
        Awaitable[None],
    ]

_SYMBOL = "TESTFS"
_TARGET = InstrumentTarget(_SYMBOL, ProductType.STOCK)
_CORP_CODE = "00999999"
_FIRST_RECEIVED = datetime(2026, 3, 10, 1, 0, tzinfo=UTC)
_SECOND_RECEIVED = datetime(2026, 3, 20, 1, 0, tzinfo=UTC)


def _line(ord_value: int, amount: Decimal | None) -> FinancialStatementLine:
    return FinancialStatementLine(
        line_seq=ord_value,
        sj_div=StatementDivision.BALANCE_SHEET,
        account_id="ifrs-full_Assets" if ord_value == 1 else None,
        account_nm=f"계정 {ord_value}",
        account_detail=None,
        ord=ord_value,
        thstrm_nm="제 57 기",
        thstrm_amount=amount,
        frmtrm_nm="제 56 기",
        frmtrm_amount=Decimal(100),
        bfefrmtrm_nm=None,
        bfefrmtrm_amount=None,
    )


def _report(rcept_no: str, received_at: datetime, amount: Decimal) -> FinancialReport:
    return FinancialReport(
        symbol=_SYMBOL,
        corp_code=_CORP_CODE,
        bsns_year=2025,
        reprt_code=ReportCode.ANNUAL,
        fs_div=FsDivision.CONSOLIDATED,
        rcept_no=rcept_no,
        currency="KRW",
        received_at=received_at,
        lines=(_line(1, amount), _line(2, None)),
    )


def _observation(
    report: FinancialReport | None,
    received_at: datetime,
) -> FinancialReportObservation:
    return FinancialReportObservation(
        raw=FinancialRawResponse(
            endpoint="/api/fnlttSinglAcntAll.json",
            request_fingerprint=f"test:financials:{uuid4()}",
            received_at=received_at,
            payload_json="{}",
        ),
        report=report,
    )


def test_same_receipt_recollection_is_idempotent() -> None:
    async def scenario(
        store: PostgresFinancialReportStore,
        reader: PostgresFinancialReportReader,
        sessions: Sessions,
    ) -> None:
        # Given
        first = _report("20260310000001", _FIRST_RECEIVED, Decimal(500))
        assert await store.save_observation(_observation(first, _FIRST_RECEIVED)) is True

        # When
        replay = replace(first, received_at=_SECOND_RECEIVED)
        assert await store.save_observation(_observation(replay, _SECOND_RECEIVED)) is True

        # Then
        current = await reader.read_current_reports(_SYMBOL)
        assert len(current) == 1
        assert current[0].version == 1
        assert current[0].rcept_no == "20260310000001"
        assert current[0].received_at == _SECOND_RECEIVED
        lines = await reader.read_report_lines(current[0].report_id)
        assert [line.ord for line in lines] == [1, 2]
        assert lines[0].thstrm_amount == Decimal(500)
        assert lines[1].thstrm_amount is None
        assert await _line_count(sessions) == 2

    anyio.run(_run_scenario, scenario)


def test_correction_creates_new_version_and_rejects_stale_receipts() -> None:
    async def scenario(
        store: PostgresFinancialReportStore,
        reader: PostgresFinancialReportReader,
        sessions: Sessions,
    ) -> None:
        # Given
        original = _report("20260310000001", _FIRST_RECEIVED, Decimal(500))
        _ = await store.save_observation(_observation(original, _FIRST_RECEIVED))

        # When
        corrected = _report("20260320000009", _SECOND_RECEIVED, Decimal(999))
        _ = await store.save_observation(_observation(corrected, _SECOND_RECEIVED))

        # Then
        current = await reader.read_current_reports(_SYMBOL)
        assert len(current) == 1
        assert current[0].version == 2
        assert current[0].rcept_no == "20260320000009"
        history = await reader.read_report_history(
            _SYMBOL, 2025, ReportCode.ANNUAL, FsDivision.CONSOLIDATED
        )
        assert [item.version for item in history] == [1, 2]
        assert history[0].superseded_at == _SECOND_RECEIVED
        old_lines = await reader.read_report_lines(history[0].report_id)
        assert old_lines[0].thstrm_amount == Decimal(500)
        assert await _line_count(sessions) == 4
        stale = _report("20260301000000", _SECOND_RECEIVED, Decimal(1))
        with pytest.raises(InvalidFinancialReportError):
            _ = await store.save_observation(
                _observation(replace(stale, received_at=_SECOND_RECEIVED), _SECOND_RECEIVED)
            )

    anyio.run(_run_scenario, scenario)


def test_missing_report_stores_raw_evidence_only() -> None:
    async def scenario(
        store: PostgresFinancialReportStore,
        reader: PostgresFinancialReportReader,
        sessions: Sessions,
    ) -> None:
        # When
        saved = await store.save_observation(_observation(None, _FIRST_RECEIVED))

        # Then
        assert saved is False
        assert await reader.read_current_reports(_SYMBOL) == ()
        assert await _line_count(sessions) == 0
        async with sessions() as session:
            raw_count = await session.scalar(
                select(func.count())
                .select_from(RawApiResponseRow)
                .where(RawApiResponseRow.operation == "financial_statements")
            )
        assert (raw_count or 0) >= 1

    anyio.run(_run_scenario, scenario)


def test_sync_status_records_success_and_failure() -> None:
    async def scenario(
        store: PostgresFinancialReportStore,
        reader: PostgresFinancialReportReader,
        sessions: Sessions,
    ) -> None:
        # When
        _ = reader
        await store.mark_started(_TARGET, _FIRST_RECEIVED)
        await store.mark_succeeded(_TARGET, _SECOND_RECEIVED)
        succeeded = await _sync_row(sessions)
        await store.mark_failed(_TARGET, _SECOND_RECEIVED, "dart_contract", "테스트 실패")
        failed = await _sync_row(sessions)

        # Then
        assert succeeded is not None
        assert succeeded.state == "success"
        assert failed is not None
        assert failed.state == "failed"
        assert failed.error_code == "dart_contract"

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: StoreScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        store = PostgresFinancialReportStore.from_connection(connection)
        reader = PostgresFinancialReportReader.from_connection(connection)
        try:
            await _seed_instrument(sessions)
            await scenario(store, reader, sessions)
        finally:
            await store.close()
            await reader.close()
            await transaction.rollback()
    await engine.dispose()


async def _seed_instrument(sessions: Sessions) -> None:
    async with sessions.begin() as session:
        _ = await session.execute(delete(InstrumentRow).where(InstrumentRow.symbol == _SYMBOL))
        session.add(
            InstrumentRow(
                id=uuid4(),
                country="KR",
                exchange="XKRX",
                symbol=_SYMBOL,
                product_type="stock",
                currency="KRW",
                name="재무제표 검증 종목",
                english_name=None,
                listed_on=None,
                delisted_on=None,
                trading_status="trading",
                source="KIS",
                source_as_of=date(2026, 8, 17),
                created_at=_FIRST_RECEIVED,
                updated_at=_FIRST_RECEIVED,
            )
        )


async def _line_count(sessions: Sessions) -> int:
    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(FinancialStatementLineRow)
            .join(
                FinancialReportRow,
                FinancialStatementLineRow.report_id == FinancialReportRow.id,
            )
            .where(FinancialReportRow.corp_code == _CORP_CODE)
        )
    return count or 0


async def _sync_row(sessions: Sessions) -> SyncStatusRow | None:
    async with sessions() as session:
        return await session.scalar(
            select(SyncStatusRow).where(
                SyncStatusRow.source == "DART",
                SyncStatusRow.operation == "financial_statements",
                SyncStatusRow.symbol == _SYMBOL,
            )
        )
