from typing import TYPE_CHECKING, final

from sqlalchemy import Select, select
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
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialStatementLine,
    FsDivision,
    ReportCode,
    StatementDivision,
    VersionedFinancialReport,
)

if TYPE_CHECKING:
    from uuid import UUID


@final
class PostgresFinancialReportReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresFinancialReportReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresFinancialReportReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def read_current_reports(self, symbol: str) -> tuple[VersionedFinancialReport, ...]:
        statement = (
            self._report_statement(symbol)
            .where(FinancialReportRow.superseded_at.is_(None))
            .order_by(
                FinancialReportRow.bsns_year,
                FinancialReportRow.reprt_code,
                FinancialReportRow.fs_div,
            )
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(_versioned_report(row[0], row[1]) for row in rows)

    async def read_report(self, report_id: UUID) -> VersionedFinancialReport | None:
        statement = (
            select(FinancialReportRow, InstrumentRow.symbol)
            .join(InstrumentRow, FinancialReportRow.instrument_id == InstrumentRow.id)
            .where(FinancialReportRow.id == report_id)
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).tuples().first()
        return _versioned_report(row[0], row[1]) if row is not None else None

    async def read_report_lines(self, report_id: UUID) -> tuple[FinancialStatementLine, ...]:
        statement = (
            select(FinancialStatementLineRow)
            .where(FinancialStatementLineRow.report_id == report_id)
            .order_by(FinancialStatementLineRow.line_seq)
        )
        async with self._sessions() as session:
            rows = tuple((await session.scalars(statement)).all())
        return tuple(_statement_line(row) for row in rows)

    async def read_report_history(
        self,
        symbol: str,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
    ) -> tuple[VersionedFinancialReport, ...]:
        statement = (
            self._report_statement(symbol)
            .where(
                FinancialReportRow.bsns_year == bsns_year,
                FinancialReportRow.reprt_code == reprt_code.value,
                FinancialReportRow.fs_div == fs_div.value,
            )
            .order_by(FinancialReportRow.version)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(_versioned_report(row[0], row[1]) for row in rows)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    @staticmethod
    def _report_statement(symbol: str) -> Select[tuple[FinancialReportRow, str]]:
        return (
            select(FinancialReportRow, InstrumentRow.symbol)
            .join(InstrumentRow, FinancialReportRow.instrument_id == InstrumentRow.id)
            .where(InstrumentRow.symbol == symbol)
        )


def _versioned_report(row: FinancialReportRow, symbol: str) -> VersionedFinancialReport:
    return VersionedFinancialReport(
        report_id=row.id,
        symbol=symbol,
        corp_code=row.corp_code,
        bsns_year=row.bsns_year,
        reprt_code=ReportCode(row.reprt_code),
        fs_div=FsDivision(row.fs_div),
        rcept_no=row.rcept_no,
        currency=row.currency,
        received_at=row.received_at,
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
    )


def _statement_line(row: FinancialStatementLineRow) -> FinancialStatementLine:
    return FinancialStatementLine(
        line_seq=row.line_seq,
        sj_div=StatementDivision(row.sj_div),
        account_id=row.account_id,
        account_nm=row.account_nm,
        account_detail=row.account_detail,
        ord=row.ord,
        thstrm_nm=row.thstrm_nm,
        thstrm_amount=row.thstrm_amount,
        frmtrm_nm=row.frmtrm_nm,
        frmtrm_amount=row.frmtrm_amount,
        bfefrmtrm_nm=row.bfefrmtrm_nm,
        bfefrmtrm_amount=row.bfefrmtrm_amount,
    )
