from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.fundamental_rows import (
    FinancialReportRow,
    FinancialStatementLineRow,
)
from auto_stock_trading.adapters.database.market_data_corporate_action_store import (
    UnknownInstrumentError,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.adapters.database.market_data_sync_statements import (
    SyncTarget,
    sync_failed,
    sync_started,
    sync_succeeded,
)
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialReport,
    FinancialReportInvariant,
    InvalidFinancialReportError,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FinancialRawResponse,
        FinancialReportObservation,
    )
    from auto_stock_trading.domain.market_data.models import InstrumentTarget

_SOURCE: Final = "DART"
_OPERATION: Final = "financial_statements"
# 스윕 진행 상태는 종목 상태와 구분해 남긴다(재무제표 계약 §유니버스 7).
_SWEEP_OPERATION: Final = "universe_financial_statements"


@final
class PostgresFinancialReportStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresFinancialReportStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresFinancialReportStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def save_observation(self, observation: FinancialReportObservation) -> bool:
        async with self._sessions.begin() as session:
            raw_id = self._add_raw_row(session, observation.raw)
            report = observation.report
            if report is None:
                return False
            instrument_id = await session.scalar(
                select(InstrumentRow.id).where(InstrumentRow.symbol == report.symbol).limit(1)
            )
            if instrument_id is None:
                raise UnknownInstrumentError(report.symbol)
            current = await session.scalar(
                select(FinancialReportRow)
                .where(
                    FinancialReportRow.instrument_id == instrument_id,
                    FinancialReportRow.bsns_year == report.bsns_year,
                    FinancialReportRow.reprt_code == report.reprt_code.value,
                    FinancialReportRow.fs_div == report.fs_div.value,
                    FinancialReportRow.superseded_at.is_(None),
                )
                .with_for_update()
            )
            if current is not None and current.rcept_no == report.rcept_no:
                if report.received_at > current.received_at:
                    current.received_at = report.received_at
                    current.raw_response_id = raw_id
                return True
            if current is not None and report.rcept_no < current.rcept_no:
                raise InvalidFinancialReportError(FinancialReportInvariant.VALIDITY)
            version = 1
            if current is not None:
                current.superseded_at = report.received_at
                version = current.version + 1
            self._add_report_rows(session, report, instrument_id, raw_id, version)
        return True

    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_started(SyncTarget(_SOURCE, _OPERATION, target.symbol), started_at)
            )

    async def mark_succeeded(self, target: InstrumentTarget, completed_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_succeeded(SyncTarget(_SOURCE, _OPERATION, target.symbol), completed_at)
            )

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_failed(
                    SyncTarget(_SOURCE, _OPERATION, target.symbol),
                    failed_at,
                    error_code,
                    error_message,
                )
            )

    async def mark_sweep_started(self, key: str, started_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_started(SyncTarget(_SOURCE, _SWEEP_OPERATION, key), started_at)
            )

    async def mark_sweep_succeeded(self, key: str, completed_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_succeeded(SyncTarget(_SOURCE, _SWEEP_OPERATION, key), completed_at)
            )

    async def mark_sweep_failed(
        self,
        key: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_failed(
                    SyncTarget(_SOURCE, _SWEEP_OPERATION, key),
                    failed_at,
                    error_code,
                    error_message,
                )
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    @staticmethod
    def _add_raw_row(session: AsyncSession, raw: FinancialRawResponse) -> UUID:
        raw_id = uuid4()
        session.add(
            RawApiResponseRow(
                id=raw_id,
                source=_SOURCE,
                operation=_OPERATION,
                endpoint=raw.endpoint,
                request_fingerprint=raw.request_fingerprint,
                received_at=raw.received_at,
                payload_json=raw.payload_json,
            )
        )
        return raw_id

    @staticmethod
    def _add_report_rows(
        session: AsyncSession,
        report: FinancialReport,
        instrument_id: UUID,
        raw_id: UUID,
        version: int,
    ) -> None:
        report_id = uuid4()
        session.add(
            FinancialReportRow(
                id=report_id,
                instrument_id=instrument_id,
                corp_code=report.corp_code,
                bsns_year=report.bsns_year,
                reprt_code=report.reprt_code.value,
                fs_div=report.fs_div.value,
                rcept_no=report.rcept_no,
                currency=report.currency,
                received_at=report.received_at,
                version=version,
                valid_from=report.received_at,
                superseded_at=None,
                raw_response_id=raw_id,
            )
        )
        for line in report.lines:
            session.add(
                FinancialStatementLineRow(
                    id=uuid4(),
                    report_id=report_id,
                    line_seq=line.line_seq,
                    sj_div=line.sj_div.value,
                    account_id=line.account_id,
                    account_nm=line.account_nm,
                    account_detail=line.account_detail,
                    ord=line.ord,
                    thstrm_nm=line.thstrm_nm,
                    thstrm_amount=line.thstrm_amount,
                    frmtrm_nm=line.frmtrm_nm,
                    frmtrm_amount=line.frmtrm_amount,
                    bfefrmtrm_nm=line.bfefrmtrm_nm,
                    bfefrmtrm_amount=line.bfefrmtrm_amount,
                )
            )
