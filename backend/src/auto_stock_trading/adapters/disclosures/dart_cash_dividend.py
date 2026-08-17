from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import final, override

_FORM_FIRST_LABEL = "1. 배당구분"
_CATEGORY_LABEL = "1. 배당구분"
_KIND_LABEL = "2. 배당종류"
_PER_SHARE_LABEL = "3. 1주당 배당금(원)"
_COMMON_SHARE_LABEL = "보통주식"
_RECORD_DATE_LABEL = "6. 배당기준일"
_PAYMENT_DATE_LABEL = "7. 배당금지급 예정일자"
_RESOLVED_ON_LABEL = "10. 이사회결의일(결정일)"
_CASH_DIVIDEND_KIND = "현금배당"
_MISSING_VALUE = "-"
_PER_SHARE_CELLS = 2


@final
@dataclass(frozen=True, slots=True)
class DartContractError(Exception):
    message: str = "DART cash dividend document did not match the expected contract"

    @override
    def __str__(self) -> str:
        return self.message


@final
@dataclass(frozen=True, slots=True)
class DartCashDividendNotice:
    dividend_category: str
    per_share_common: Decimal
    record_date: date | None
    payment_date: date | None
    resolved_on: date


@final
class _TableExtractor(HTMLParser):
    tables: list[list[list[str]]]

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._table_depth = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self.tables.append([])
        if self._table_depth != 1:
            return
        if tag == "tr":
            self._row = []
        elif tag == "td":
            self._cell = []

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._table_depth > 0:
            self._table_depth -= 1
            return
        if self._table_depth != 1:
            return
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row.append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None

    @override
    def handle_data(self, data: str) -> None:
        if self._table_depth == 1 and self._cell is not None:
            self._cell.append(data.replace("\xa0", " "))


def parse_cash_dividend_document(document_html: str) -> DartCashDividendNotice:
    rows = _dividend_form_rows(document_html)
    kind = _required_value(rows, _KIND_LABEL)
    if kind != _CASH_DIVIDEND_KIND:
        message = f"unsupported dividend kind: {kind}"
        raise DartContractError(message)
    resolved_on = _required_date(rows, _RESOLVED_ON_LABEL)
    return DartCashDividendNotice(
        dividend_category=_required_value(rows, _CATEGORY_LABEL),
        per_share_common=_common_per_share(rows),
        record_date=_optional_date(rows, _RECORD_DATE_LABEL),
        payment_date=_optional_date(rows, _PAYMENT_DATE_LABEL),
        resolved_on=resolved_on,
    )


def _dividend_form_rows(document_html: str) -> list[list[str]]:
    extractor = _TableExtractor()
    extractor.feed(document_html)
    forms = [
        table
        for table in extractor.tables
        if table and table[0] and table[0][0] == _FORM_FIRST_LABEL
    ]
    if len(forms) != 1:
        message = f"expected one dividend form table, found {len(forms)}"
        raise DartContractError(message)
    return forms[0]


def _required_value(rows: list[list[str]], label: str) -> str:
    values = [row[1:] for row in rows if row and row[0] == label]
    if len(values) != 1 or len(values[0]) != 1:
        message = f"expected one value for label: {label}"
        raise DartContractError(message)
    return values[0][0]


def _common_per_share(rows: list[list[str]]) -> Decimal:
    values = [row[1:] for row in rows if row and row[0] == _PER_SHARE_LABEL]
    if (
        len(values) != 1
        or len(values[0]) != _PER_SHARE_CELLS
        or values[0][0] != _COMMON_SHARE_LABEL
    ):
        message = f"expected common-share value for label: {_PER_SHARE_LABEL}"
        raise DartContractError(message)
    text = values[0][1].replace(",", "")
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        message = f"invalid per-share dividend amount: {text}"
        raise DartContractError(message) from error
    return amount


def _optional_date(rows: list[list[str]], label: str) -> date | None:
    text = _required_value(rows, label)
    if text == _MISSING_VALUE:
        return None
    return _parse_date(text, label)


def _required_date(rows: list[list[str]], label: str) -> date:
    return _parse_date(_required_value(rows, label), label)


def _parse_date(text: str, label: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        message = f"invalid date for label {label}: {text}"
        raise DartContractError(message) from error
