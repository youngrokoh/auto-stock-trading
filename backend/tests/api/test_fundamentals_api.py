from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, final
from uuid import UUID

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialStatementLine,
    FsDivision,
    ReportCode,
    StatementDivision,
    VersionedFinancialReport,
)
from auto_stock_trading.domain.market_data.models import (
    Instrument,
    ProductType,
    Quote,
    VersionedDailyBar,
)
from auto_stock_trading.settings.runtime import Environment, Settings

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.minute_bars import VersionedMinuteBar

_SYMBOL = "005930"
_REPORT_ID = UUID(int=11)
_PREVIOUS_REPORT_ID = UUID(int=12)
_RECEIVED_AT = datetime(2026, 3, 10, 1, 0, tzinfo=UTC)
_CORRECTED_AT = datetime(2026, 3, 20, 1, 0, tzinfo=UTC)


@final
class StubProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@final
class StubMarketDataReader:
    async def instruments(self) -> tuple[Instrument, ...]:
        result = await self.instrument(_SYMBOL)
        assert result is not None
        return (result,)

    async def instrument(self, symbol: str) -> Instrument | None:
        if symbol != _SYMBOL:
            return None
        return Instrument(
            country="KR",
            exchange="XKRX",
            symbol=symbol,
            product_type=ProductType.STOCK,
            currency="KRW",
            name="삼성전자",
            english_name=None,
            listed_on=None,
            delisted_on=None,
            trading_status="active",
            source="KIS",
            source_as_of=date(2026, 8, 17),
        )

    async def quote(self, symbol: str) -> Quote | None:
        _ = symbol
        return None

    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[VersionedDailyBar, ...]:
        _ = (symbol, start_date, end_date)
        return ()

    async def minute_bars(
        self,
        symbol: str,
        trading_date: date,
    ) -> tuple[VersionedMinuteBar, ...]:
        _ = (symbol, trading_date)
        return ()

    async def close(self) -> None:
        return None


def _versioned(
    report_id: UUID, version: int, superseded_at: datetime | None
) -> VersionedFinancialReport:
    return VersionedFinancialReport(
        report_id=report_id,
        symbol=_SYMBOL,
        corp_code="00126380",
        bsns_year=2025,
        reprt_code=ReportCode.ANNUAL,
        fs_div=FsDivision.CONSOLIDATED,
        rcept_no="20260310002820" if version == 1 else "20260320000009",
        currency="KRW",
        received_at=_RECEIVED_AT if version == 1 else _CORRECTED_AT,
        version=version,
        valid_from=_RECEIVED_AT if version == 1 else _CORRECTED_AT,
        superseded_at=superseded_at,
    )


_CURRENT = _versioned(_REPORT_ID, 2, None)
_PREVIOUS = _versioned(_PREVIOUS_REPORT_ID, 1, _CORRECTED_AT)


@final
class StubFinancialReportReader:
    async def read_current_reports(self, symbol: str) -> tuple[VersionedFinancialReport, ...]:
        return (_CURRENT,) if symbol == _SYMBOL else ()

    async def read_report(self, report_id: UUID) -> VersionedFinancialReport | None:
        return _CURRENT if report_id == _REPORT_ID else None

    async def read_report_lines(self, report_id: UUID) -> tuple[FinancialStatementLine, ...]:
        if report_id != _REPORT_ID:
            return ()
        return (
            FinancialStatementLine(
                line_seq=1,
                sj_div=StatementDivision.BALANCE_SHEET,
                account_id="ifrs-full_Assets",
                account_nm="자산총계",
                account_detail=None,
                ord=1,
                thstrm_nm="제 57 기",
                thstrm_amount=Decimal(566942110000000),
                frmtrm_nm="제 56 기",
                frmtrm_amount=Decimal(514531948000000),
                bfefrmtrm_nm=None,
                bfefrmtrm_amount=None,
            ),
        )

    async def read_report_history(
        self,
        symbol: str,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
    ) -> tuple[VersionedFinancialReport, ...]:
        if (
            symbol != _SYMBOL
            or bsns_year != 2025
            or reprt_code is not ReportCode.ANNUAL
            or fs_div is not FsDivision.CONSOLIDATED
        ):
            return ()
        return (_PREVIOUS, _CURRENT)

    async def close(self) -> None:
        return None


def _client() -> TestClient:
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        market_data_reader_factory=StubMarketDataReader,
        financial_report_reader_factory=StubFinancialReportReader,
    )
    return TestClient(app)


_EXPECTED_CURRENT: dict[str, object] = {
    "report_id": str(_REPORT_ID),
    "symbol": _SYMBOL,
    "corp_code": "00126380",
    "bsns_year": 2025,
    "reprt_code": "11011",
    "fs_div": "CFS",
    "rcept_no": "20260320000009",
    "currency": "KRW",
    "received_at": "2026-03-20T01:00:00Z",
    "version": 2,
    "valid_from": "2026-03-20T01:00:00Z",
    "superseded_at": None,
}
_EXPECTED_PREVIOUS: dict[str, object] = {
    "report_id": str(_PREVIOUS_REPORT_ID),
    "symbol": _SYMBOL,
    "corp_code": "00126380",
    "bsns_year": 2025,
    "reprt_code": "11011",
    "fs_div": "CFS",
    "rcept_no": "20260310002820",
    "currency": "KRW",
    "received_at": "2026-03-10T01:00:00Z",
    "version": 1,
    "valid_from": "2026-03-10T01:00:00Z",
    "superseded_at": "2026-03-20T01:00:00Z",
}


def test_financial_reports_expose_receipt_evidence_and_lines() -> None:
    with _client() as client:
        reports = client.get(f"/api/fundamentals/instruments/{_SYMBOL}/financial-reports")
        detail = client.get(f"/api/fundamentals/financial-reports/{_REPORT_ID}")

    assert reports.status_code == 200
    assert reports.json() == {
        "symbol": _SYMBOL,
        "source": "DART",
        "reports": [_EXPECTED_CURRENT],
    }
    assert detail.status_code == 200
    assert detail.json() == {
        "source": "DART",
        "report": _EXPECTED_CURRENT,
        "lines": [
            {
                "line_seq": 1,
                "sj_div": "BS",
                "account_id": "ifrs-full_Assets",
                "account_nm": "자산총계",
                "account_detail": None,
                "ord": 1,
                "thstrm_nm": "제 57 기",
                "thstrm_amount": "566942110000000",
                "frmtrm_nm": "제 56 기",
                "frmtrm_amount": "514531948000000",
                "bfefrmtrm_nm": None,
                "bfefrmtrm_amount": None,
            }
        ],
    }


def test_financial_report_history_returns_all_versions() -> None:
    with _client() as client:
        history = client.get(
            f"/api/fundamentals/instruments/{_SYMBOL}/financial-reports/history",
            params={"bsns_year": 2025, "reprt_code": "11011", "fs_div": "CFS"},
        )

    assert history.status_code == 200
    assert history.json() == {
        "symbol": _SYMBOL,
        "source": "DART",
        "reports": [_EXPECTED_PREVIOUS, _EXPECTED_CURRENT],
    }


def test_fundamentals_endpoints_reject_unknown_targets() -> None:
    with _client() as client:
        unknown_symbol = client.get("/api/fundamentals/instruments/999999/financial-reports")
        unknown_report = client.get(f"/api/fundamentals/financial-reports/{UUID(int=99)}")
        invalid_code = client.get(
            f"/api/fundamentals/instruments/{_SYMBOL}/financial-reports/history",
            params={"bsns_year": 2025, "reprt_code": "bogus", "fs_div": "CFS"},
        )

    assert unknown_symbol.status_code == 404
    assert unknown_report.status_code == 404
    assert invalid_code.status_code == 422
