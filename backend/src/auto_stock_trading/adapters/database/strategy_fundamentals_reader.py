"""종합 순위 전략의 시점 정합 재무 입력 조회(백테스트 계약 v3).

지표 정의는 도메인 순수 함수(`compute_annual_indicators`·`basic_eps`)를 그대로 쓴다. 전략이
재무 지표를 다시 정의하면 화면과 백테스트가 갈라진다.

라인은 `IS`·`CIS`·`BS`만 읽는다. 계약이 정의한 모든 입력 계정이 이 세 구분에 있고, `SCE`는
같은 계정 ID를 자본 구성요소별 여러 행이 공유해 양만 늘린다.
"""

from typing import TYPE_CHECKING, Final, final

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
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialStatementLine,
    FsDivision,
    ReportCode,
    StatementDivision,
    VersionedFinancialReport,
)
from auto_stock_trading.domain.fundamentals.indicators import compute_annual_indicators
from auto_stock_trading.domain.fundamentals.valuation import basic_eps
from auto_stock_trading.domain.strategies.composite_rank import (
    AnnualFact,
    SymbolFundamentals,
    disclosure_filed_on,
)

if TYPE_CHECKING:
    from uuid import UUID

_ROE_KEY: Final = "roe"
_LINE_DIVISIONS: Final = (
    StatementDivision.INCOME_STATEMENT.value,
    StatementDivision.COMPREHENSIVE_INCOME.value,
    StatementDivision.BALANCE_SHEET.value,
)


@final
class PostgresStrategyFundamentalsReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresStrategyFundamentalsReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresStrategyFundamentalsReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def read_annual_facts(self, symbols: tuple[str, ...]) -> tuple[SymbolFundamentals, ...]:
        """연결 사업보고서의 모든 저장 버전을 종목별로 돌려준다.

        정정 전 버전도 포함한다. 시점 정합 선택이 접수번호로 그 시점의 최신 버전을 고른다.
        """
        if not symbols:
            return ()
        reports = await self._reports(symbols)
        lines = await self._lines(tuple(report.report_id for report in reports))
        facts: dict[str, list[AnnualFact]] = {}
        for report in reports:
            indicators = compute_annual_indicators(report, lines.get(report.report_id, ()))
            roe = next(
                (item.value for item in indicators.indicators if item.key == _ROE_KEY),
                None,
            )
            facts.setdefault(report.symbol, []).append(
                AnnualFact(
                    bsns_year=report.bsns_year,
                    reprt_code=report.reprt_code.value,
                    fs_div=report.fs_div.value,
                    rcept_no=report.rcept_no,
                    filed_on=disclosure_filed_on(report.rcept_no),
                    roe=roe,
                    eps=basic_eps(lines.get(report.report_id, ())),
                )
            )
        return tuple(
            SymbolFundamentals(symbol=symbol, facts=tuple(items))
            for symbol, items in sorted(facts.items())
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    async def _reports(self, symbols: tuple[str, ...]) -> tuple[VersionedFinancialReport, ...]:
        statement = (
            select(FinancialReportRow, InstrumentRow.symbol)
            .join(InstrumentRow, FinancialReportRow.instrument_id == InstrumentRow.id)
            .where(
                InstrumentRow.symbol.in_(symbols),
                FinancialReportRow.reprt_code == ReportCode.ANNUAL.value,
                FinancialReportRow.fs_div == FsDivision.CONSOLIDATED.value,
            )
            .order_by(
                InstrumentRow.symbol,
                FinancialReportRow.bsns_year,
                FinancialReportRow.version,
            )
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(
            VersionedFinancialReport(
                report_id=row[0].id,
                symbol=row[1],
                corp_code=row[0].corp_code,
                bsns_year=row[0].bsns_year,
                reprt_code=ReportCode(row[0].reprt_code),
                fs_div=FsDivision(row[0].fs_div),
                rcept_no=row[0].rcept_no,
                currency=row[0].currency,
                received_at=row[0].received_at,
                version=row[0].version,
                valid_from=row[0].valid_from,
                superseded_at=row[0].superseded_at,
            )
            for row in rows
        )

    async def _lines(
        self,
        report_ids: tuple[UUID, ...],
    ) -> dict[UUID, tuple[FinancialStatementLine, ...]]:
        if not report_ids:
            return {}
        statement = (
            select(FinancialStatementLineRow)
            .where(
                FinancialStatementLineRow.report_id.in_(report_ids),
                FinancialStatementLineRow.sj_div.in_(_LINE_DIVISIONS),
            )
            .order_by(FinancialStatementLineRow.report_id, FinancialStatementLineRow.line_seq)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        grouped: dict[UUID, list[FinancialStatementLine]] = {}
        for row in rows:
            grouped.setdefault(row.report_id, []).append(
                FinancialStatementLine(
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
            )
        return {report_id: tuple(items) for report_id, items in grouped.items()}
