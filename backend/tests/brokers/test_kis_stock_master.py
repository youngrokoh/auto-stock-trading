from datetime import UTC, datetime
from typing import Final

from auto_stock_trading.adapters.brokers.kis_master_files import (
    parse_kospi_universe_profiles,
)

_NOW: Final = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)


def _record(
    symbol: str,
    isin: str,
    name: str,
    group: str,
    sector: str,
) -> bytes:
    """실측 288바이트 레코드. 업종 코드는 [79], 그룹코드는 [61:63]이다."""
    head = symbol.encode("cp949").ljust(9) + isin.encode("cp949")
    name_bytes = name.encode("cp949").ljust(40)
    middle = group.encode("cp949") + b"1002700130000 NN"
    tail = sector.encode("cp949") + b"Y" * 2 + b"0" * 205
    return head + name_bytes + middle + tail


def test_universe_parse_keeps_kospi200_common_stocks_in_file_order() -> None:
    content = b"\n".join(
        (
            _record("005930", "KR7005930003", "삼성전자", "ST", "5"),
            _record("035420", "KR7035420009", "NAVER", "ST", "B"),
            b"",
        )
    )

    profiles = parse_kospi_universe_profiles(content, _NOW)

    assert [(p.symbol, p.isin, p.name, p.sector_code) for p in profiles] == [
        ("005930", "KR7005930003", "삼성전자", "5"),
        ("035420", "KR7035420009", "NAVER", "B"),
    ]
    assert profiles[0].source == "KIS_MASTER"
    assert profiles[0].received_at == _NOW


def test_universe_parse_excludes_non_members_other_groups_and_preferred_shares() -> None:
    content = b"\n".join(
        (
            _record("005930", "KR7005930003", "삼성전자", "ST", "5"),
            # KOSPI200 미포함(섹터코드 0)
            _record("000320", "KR7000320005", "노루홀딩스", "ST", "0"),
            # ETF는 ETF 계약이 담당한다
            _record("069500", "KR7069500007", "KODEX 200", "EF", "0"),
            # ETN
            _record("500001", "KR7500001004", "삼성 레버리지", "EN", "0"),
            # 우선주는 6번째 자리가 0이 아니다
            _record("005935", "KR7005931001", "삼성전자우", "ST", "5"),
        )
    )

    profiles = parse_kospi_universe_profiles(content, _NOW)

    assert [p.symbol for p in profiles] == ["005930"]


def test_universe_parse_skips_short_or_broken_lines() -> None:
    content = b"\n".join(
        (
            b"garbage",
            _record("005930", "KR7005930003", "삼성전자", "ST", "5"),
        )
    )

    profiles = parse_kospi_universe_profiles(content, _NOW)

    assert [p.symbol for p in profiles] == ["005930"]
