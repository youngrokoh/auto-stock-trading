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


_ANNUAL_2024_ID = UUID(int=21)
_ANNUAL_2025_ID = UUID(int=22)
_SEPARATE_2025_ID = UUID(int=23)
_INTERIM_2026_ID = UUID(int=24)


def _indicator_report(
    report_id: UUID,
    bsns_year: int,
    reprt_code: ReportCode,
    fs_div: FsDivision,
    rcept_no: str,
) -> VersionedFinancialReport:
    return VersionedFinancialReport(
        report_id=report_id,
        symbol=_SYMBOL,
        corp_code="00126380",
        bsns_year=bsns_year,
        reprt_code=reprt_code,
        fs_div=fs_div,
        rcept_no=rcept_no,
        currency="KRW",
        received_at=_RECEIVED_AT,
        version=1,
        valid_from=_RECEIVED_AT,
        superseded_at=None,
    )


def _statement_line(
    line_seq: int,
    sj_div: StatementDivision,
    account_id: str,
    account_nm: str,
    *,
    amounts: tuple[str, str],
) -> FinancialStatementLine:
    return FinancialStatementLine(
        line_seq=line_seq,
        sj_div=sj_div,
        account_id=account_id,
        account_nm=account_nm,
        account_detail=None,
        ord=line_seq,
        thstrm_nm="제 57 기",
        thstrm_amount=Decimal(amounts[0]),
        frmtrm_nm="제 56 기",
        frmtrm_amount=Decimal(amounts[1]),
        bfefrmtrm_nm=None,
        bfefrmtrm_amount=None,
    )


def _indicator_lines() -> tuple[FinancialStatementLine, ...]:
    bs = StatementDivision.BALANCE_SHEET
    is_ = StatementDivision.INCOME_STATEMENT
    return (
        _statement_line(1, bs, "ifrs-full_CurrentAssets", "유동자산", amounts=("900", "700")),
        _statement_line(2, bs, "ifrs-full_Assets", "자산총계", amounts=("2200", "1800")),
        _statement_line(3, bs, "ifrs-full_CurrentLiabilities", "유동부채", amounts=("600", "500")),
        _statement_line(4, bs, "ifrs-full_Liabilities", "부채총계", amounts=("800", "850")),
        _statement_line(
            5,
            bs,
            "ifrs-full_EquityAttributableToOwnersOfParent",
            "지배기업 소유주지분",
            amounts=("1050", "950"),
        ),
        _statement_line(6, bs, "ifrs-full_Equity", "자본총계", amounts=("1600", "950")),
        _statement_line(7, is_, "ifrs-full_Revenue", "매출액", amounts=("1200", "1000")),
        _statement_line(8, is_, "dart_OperatingIncomeLoss", "영업이익", amounts=("150", "100")),
        _statement_line(9, is_, "ifrs-full_ProfitLoss", "당기순이익", amounts=("110", "88")),
        _statement_line(
            10,
            is_,
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분",
            amounts=("100", "80"),
        ),
    )


@final
class StubIndicatorReportReader:
    async def read_current_reports(self, symbol: str) -> tuple[VersionedFinancialReport, ...]:
        if symbol != _SYMBOL:
            return ()
        return (
            _indicator_report(
                _INTERIM_2026_ID,
                2026,
                ReportCode.HALF_YEAR,
                FsDivision.CONSOLIDATED,
                "20260814000004",
            ),
            _indicator_report(
                _ANNUAL_2025_ID, 2025, ReportCode.ANNUAL, FsDivision.CONSOLIDATED, "20260310000002"
            ),
            _indicator_report(
                _ANNUAL_2024_ID, 2024, ReportCode.ANNUAL, FsDivision.CONSOLIDATED, "20250311000001"
            ),
            _indicator_report(
                _SEPARATE_2025_ID, 2025, ReportCode.ANNUAL, FsDivision.SEPARATE, "20260310000003"
            ),
        )

    async def read_report(self, report_id: UUID) -> VersionedFinancialReport | None:
        _ = report_id
        return None

    async def read_report_lines(self, report_id: UUID) -> tuple[FinancialStatementLine, ...]:
        if report_id in (_ANNUAL_2024_ID, _ANNUAL_2025_ID):
            return _indicator_lines()
        if report_id == _SEPARATE_2025_ID:
            return tuple(
                line
                for line in _indicator_lines()
                if line.account_id
                not in (
                    "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                    "ifrs-full_EquityAttributableToOwnersOfParent",
                )
            )
        return ()

    async def read_report_history(
        self,
        symbol: str,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
    ) -> tuple[VersionedFinancialReport, ...]:
        _ = (symbol, bsns_year, reprt_code, fs_div)
        return ()

    async def close(self) -> None:
        return None


def _indicator_client() -> TestClient:
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        market_data_reader_factory=StubMarketDataReader,
        financial_report_reader_factory=StubIndicatorReportReader,
    )
    return TestClient(app)


def _input_json(
    name: str,
    sj_div: str,
    account_id: str,
    period: str,
    amount: str | None,
) -> dict[str, object]:
    return {
        "name": name,
        "sj_div": sj_div,
        "account_id": account_id,
        "period": period,
        "amount": amount,
    }


def _indicator_json(
    head: tuple[str, str, str],
    formula: str,
    inputs: list[dict[str, object]],
    *,
    value: str | None,
    unavailable_reason: str | None = None,
) -> dict[str, object]:
    key, name, category = head
    return {
        "key": key,
        "name": name,
        "category": category,
        "unit": "percent",
        "formula": formula,
        "inputs": inputs,
        "value": value,
        "unavailable_reason": unavailable_reason,
    }


def _figure_json(
    key: str, name: str, sj_div: str, account_id: str, amount: str | None
) -> dict[str, object]:
    return {
        "key": key,
        "name": name,
        "sj_div": sj_div,
        "account_id": account_id,
        "amount": amount,
    }


def _average_base_formula(numerator: str, base: str) -> str:
    return f"당기 {numerator} ÷ ((기초 {base} + 기말 {base}) ÷ 2) × 100"


def _growth_json(
    key: str, name: str, subject: str, account_id: str, value: str
) -> dict[str, object]:
    amounts = {
        "ifrs-full_Revenue": ("1200", "1000"),
        "dart_OperatingIncomeLoss": ("150", "100"),
        "ifrs-full_ProfitLoss": ("110", "88"),
    }[account_id]
    return _indicator_json(
        (key, name, "growth"),
        f"(당기 {subject} - 전기 {subject}) ÷ |전기 {subject}| × 100",
        [
            _input_json(subject, "IS", account_id, "thstrm", amounts[0]),
            _input_json(subject, "IS", account_id, "frmtrm", amounts[1]),
        ],
        value=value,
    )


def _cfs_indicators_json() -> list[dict[str, object]]:
    return [
        _growth_json("revenue_growth", "매출액증가율", "매출액", "ifrs-full_Revenue", "20.00"),
        _growth_json(
            "operating_income_growth",
            "영업이익증가율",
            "영업이익",
            "dart_OperatingIncomeLoss",
            "50.00",
        ),
        _growth_json(
            "net_income_growth", "순이익증가율", "당기순이익", "ifrs-full_ProfitLoss", "25.00"
        ),
        _indicator_json(
            ("operating_margin", "영업이익률", "profitability"),
            "당기 영업이익 ÷ 당기 매출액 × 100",
            [
                _input_json("영업이익", "IS", "dart_OperatingIncomeLoss", "thstrm", "150"),
                _input_json("매출액", "IS", "ifrs-full_Revenue", "thstrm", "1200"),
            ],
            value="12.50",
        ),
        _indicator_json(
            ("net_margin", "순이익률", "profitability"),
            "당기 당기순이익 ÷ 당기 매출액 × 100",
            [
                _input_json("당기순이익", "IS", "ifrs-full_ProfitLoss", "thstrm", "110"),
                _input_json("매출액", "IS", "ifrs-full_Revenue", "thstrm", "1200"),
            ],
            value="9.17",
        ),
        _indicator_json(
            ("roe", "ROE(지배주주)", "profitability"),
            _average_base_formula("지배주주순이익", "지배기업 소유주지분"),
            [
                _input_json(
                    "지배주주순이익",
                    "IS",
                    "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                    "thstrm",
                    "100",
                ),
                _input_json(
                    "지배기업 소유주지분",
                    "BS",
                    "ifrs-full_EquityAttributableToOwnersOfParent",
                    "frmtrm",
                    "950",
                ),
                _input_json(
                    "지배기업 소유주지분",
                    "BS",
                    "ifrs-full_EquityAttributableToOwnersOfParent",
                    "thstrm",
                    "1050",
                ),
            ],
            value="10.00",
        ),
        _indicator_json(
            ("roa", "ROA", "profitability"),
            _average_base_formula("당기순이익", "자산총계"),
            [
                _input_json("당기순이익", "IS", "ifrs-full_ProfitLoss", "thstrm", "110"),
                _input_json("자산총계", "BS", "ifrs-full_Assets", "frmtrm", "1800"),
                _input_json("자산총계", "BS", "ifrs-full_Assets", "thstrm", "2200"),
            ],
            value="5.50",
        ),
        _indicator_json(
            ("debt_ratio", "부채비율", "stability"),
            "당기 부채총계 ÷ 당기 자본총계 × 100",
            [
                _input_json("부채총계", "BS", "ifrs-full_Liabilities", "thstrm", "800"),
                _input_json("자본총계", "BS", "ifrs-full_Equity", "thstrm", "1600"),
            ],
            value="50.00",
        ),
        _indicator_json(
            ("current_ratio", "유동비율", "stability"),
            "당기 유동자산 ÷ 당기 유동부채 × 100",
            [
                _input_json("유동자산", "BS", "ifrs-full_CurrentAssets", "thstrm", "900"),
                _input_json("유동부채", "BS", "ifrs-full_CurrentLiabilities", "thstrm", "600"),
            ],
            value="150.00",
        ),
    ]


def _cfs_figures_json() -> list[dict[str, object]]:
    return [
        _figure_json("revenue", "매출액", "IS", "ifrs-full_Revenue", "1200"),
        _figure_json("operating_income", "영업이익", "IS", "dart_OperatingIncomeLoss", "150"),
        _figure_json("net_income", "당기순이익", "IS", "ifrs-full_ProfitLoss", "110"),
        _figure_json(
            "net_income_owners",
            "지배주주순이익",
            "IS",
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "100",
        ),
        _figure_json("assets", "자산총계", "BS", "ifrs-full_Assets", "2200"),
        _figure_json("liabilities", "부채총계", "BS", "ifrs-full_Liabilities", "800"),
        _figure_json("equity", "자본총계", "BS", "ifrs-full_Equity", "1600"),
    ]


def _year_json(
    bsns_year: int,
    fs_div: str,
    rcept_no: str,
    figures: list[dict[str, object]],
    indicators: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "bsns_year": bsns_year,
        "reprt_code": "11011",
        "fs_div": fs_div,
        "rcept_no": rcept_no,
        "currency": "KRW",
        "version": 1,
        "figures": figures,
        "indicators": indicators,
    }


def test_financial_indicators_cover_annual_reports_with_formula_and_sources() -> None:
    with _indicator_client() as client:
        response = client.get(f"/api/fundamentals/instruments/{_SYMBOL}/indicators")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": _SYMBOL,
        "source": "DART",
        "fs_div": "CFS",
        "years": [
            _year_json(2024, "CFS", "20250311000001", _cfs_figures_json(), _cfs_indicators_json()),
            _year_json(2025, "CFS", "20260310000002", _cfs_figures_json(), _cfs_indicators_json()),
        ],
    }


def _ofs_figures_json() -> list[dict[str, object]]:
    return [
        {**figure, "amount": None} if figure["key"] == "net_income_owners" else figure
        for figure in _cfs_figures_json()
    ]


def _ofs_indicators_json() -> list[dict[str, object]]:
    roe_unavailable = _indicator_json(
        ("roe", "ROE(지배주주)", "profitability"),
        "당기 지배주주순이익 ÷ ((기초 지배기업 소유주지분 + 기말 지배기업 소유주지분) ÷ 2) × 100",
        [
            _input_json(
                "지배주주순이익",
                "IS",
                "ifrs-full_ProfitLossAttributableToOwnersOfParent",
                "thstrm",
                None,
            ),
            _input_json(
                "지배기업 소유주지분",
                "BS",
                "ifrs-full_EquityAttributableToOwnersOfParent",
                "frmtrm",
                None,
            ),
            _input_json(
                "지배기업 소유주지분",
                "BS",
                "ifrs-full_EquityAttributableToOwnersOfParent",
                "thstrm",
                None,
            ),
        ],
        value=None,
        unavailable_reason="MISSING_ACCOUNT",
    )
    return [
        roe_unavailable if indicator["key"] == "roe" else indicator
        for indicator in _cfs_indicators_json()
    ]


def test_financial_indicators_for_separate_statements_fail_closed_without_owner_accounts() -> None:
    with _indicator_client() as client:
        response = client.get(
            f"/api/fundamentals/instruments/{_SYMBOL}/indicators",
            params={"fs_div": "OFS"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "symbol": _SYMBOL,
        "source": "DART",
        "fs_div": "OFS",
        "years": [
            _year_json(2025, "OFS", "20260310000003", _ofs_figures_json(), _ofs_indicators_json()),
        ],
    }


def test_financial_indicators_reject_unknown_symbol_and_invalid_fs_div() -> None:
    with _indicator_client() as client:
        unknown = client.get("/api/fundamentals/instruments/999999/indicators")
        invalid = client.get(
            f"/api/fundamentals/instruments/{_SYMBOL}/indicators",
            params={"fs_div": "bogus"},
        )

    assert unknown.status_code == 404
    assert invalid.status_code == 422
