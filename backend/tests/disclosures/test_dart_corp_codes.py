from datetime import UTC, datetime
from typing import Final

from auto_stock_trading.adapters.disclosures.dart_corp_codes import parse_corp_codes

_NOW: Final = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _entry(corp_code: str, corp_name: str, stock_code: str) -> str:
    return (
        "<list>"
        f"<corp_code>{corp_code}</corp_code>"
        f"<corp_name>{corp_name}</corp_name>"
        "<corp_eng_name>Sample</corp_eng_name>"
        f"<stock_code>{stock_code}</stock_code>"
        "<modify_date>20260814</modify_date>"
        "</list>"
    )


def _document(*entries: str) -> bytes:
    body = "".join(entries)
    return f'<?xml version="1.0" encoding="UTF-8"?><result>{body}</result>'.encode()


def test_only_listed_companies_with_a_six_digit_stock_code_are_kept() -> None:
    content = _document(
        _entry("00126380", "삼성전자", "005930"),
        # 비상장 법인은 종목코드 자리가 공백이다(실측 형식).
        _entry("00434003", "비상장회사", "         "),
        _entry("00164779", "SK하이닉스", "000660"),
    )

    codes = parse_corp_codes(content, _NOW)

    assert [(item.symbol, item.corp_code, item.corp_name) for item in codes] == [
        ("005930", "00126380", "삼성전자"),
        ("000660", "00164779", "SK하이닉스"),
    ]
    assert codes[0].source == "DART"
    assert codes[0].received_at == _NOW


def test_the_last_entry_wins_when_a_stock_code_repeats() -> None:
    """같은 종목코드가 두 번 나오면 뒤 항목이 현재 사실이다(파일 순서를 신뢰한다)."""
    content = _document(
        _entry("00000001", "구법인", "005930"),
        _entry("00126380", "삼성전자", "005930"),
    )

    codes = parse_corp_codes(content, _NOW)

    assert [(item.symbol, item.corp_code) for item in codes] == [("005930", "00126380")]


def test_a_missing_or_malformed_stock_code_is_skipped_without_failing() -> None:
    content = _document(
        "<list><corp_code>00000002</corp_code><corp_name>필드없음</corp_name></list>",
        _entry("00000003", "짧은코드", "12345"),
        _entry("00126380", "삼성전자", "005930"),
    )

    codes = parse_corp_codes(content, _NOW)

    assert [item.symbol for item in codes] == ["005930"]
