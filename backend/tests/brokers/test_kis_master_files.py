from datetime import UTC, datetime

from auto_stock_trading.adapters.brokers.kis_master_files import parse_kospi_etf_profiles

_NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


def _record(symbol: str, isin: str, name: str, group: str) -> bytes:
    head = symbol.encode("cp949").ljust(9) + isin.encode("cp949")
    name_bytes = name.encode("cp949").ljust(40)
    tail = group.encode("cp949") + b"0" * 223
    return head + name_bytes + tail


def test_master_parse_keeps_only_etf_rows_in_file_order() -> None:
    content = b"\n".join(
        (
            _record("069500", "KR7069500007", "KODEX 200", "EF"),
            _record("005930", "KR7005930003", "삼성전자", "ST"),
            _record("0000H0", "KR70000H0005", "KODEX 인도Nifty미드캡100", "EF"),
            b"",
        )
    )

    profiles = parse_kospi_etf_profiles(content, _NOW)

    assert [(p.symbol, p.isin, p.name) for p in profiles] == [
        ("069500", "KR7069500007", "KODEX 200"),
        ("0000H0", "KR70000H0005", "KODEX 인도Nifty미드캡100"),
    ]
    assert profiles[0].source == "KIS_MASTER"
    assert profiles[0].received_at == _NOW


def test_master_parse_skips_short_or_broken_lines() -> None:
    content = b"\n".join(
        (
            b"garbage",
            _record("069500", "KR7069500007", "KODEX 200", "EF"),
        )
    )

    profiles = parse_kospi_etf_profiles(content, _NOW)

    assert [p.symbol for p in profiles] == ["069500"]
