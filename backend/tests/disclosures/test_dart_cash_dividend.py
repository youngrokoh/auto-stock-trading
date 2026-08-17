from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from auto_stock_trading.adapters.disclosures.dart_cash_dividend import (
    DartContractError,
    parse_cash_dividend_document,
)

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "dart" / "20260430800106.html"


def _document() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_parses_official_quarterly_cash_dividend_document() -> None:
    notice = parse_cash_dividend_document(_document())

    assert notice.dividend_category == "분기배당"
    assert notice.per_share_common == Decimal(372)
    assert notice.record_date == date(2026, 3, 31)
    assert notice.payment_date == date(2026, 5, 29)
    assert notice.resolved_on == date(2026, 4, 30)


def test_pending_record_date_is_parsed_as_missing() -> None:
    document = _document().replace("2026-03-31", "-")

    notice = parse_cash_dividend_document(document)

    assert notice.record_date is None


def test_in_kind_dividend_is_rejected() -> None:
    document = _document().replace(">현금배당<", ">현물배당<")

    with pytest.raises(DartContractError):
        _ = parse_cash_dividend_document(document)


def test_missing_board_resolution_label_is_rejected() -> None:
    document = _document().replace("10. 이사회결의일(결정일)", "10. 알수없는항목")

    with pytest.raises(DartContractError):
        _ = parse_cash_dividend_document(document)


def test_malformed_dividend_amount_is_rejected() -> None:
    document = _document().replace(
        'text-align:right;">372</span>',
        'text-align:right;">미정</span>',
    )

    with pytest.raises(DartContractError):
        _ = parse_cash_dividend_document(document)


def test_document_without_dividend_form_table_is_rejected() -> None:
    with pytest.raises(DartContractError):
        _ = parse_cash_dividend_document("<html><body><p>본문 없음</p></body></html>")
