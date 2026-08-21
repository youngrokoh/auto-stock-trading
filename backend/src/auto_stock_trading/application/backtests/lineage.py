"""입력 계보 해시. 단일 종목 실행과 다종목 실행이 같은 방식으로 계산한다."""

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from auto_stock_trading.domain.market_data.corporate_actions import (
        VersionedCorporateAction,
    )
    from auto_stock_trading.domain.market_data.models import VersionedDailyBar
    from auto_stock_trading.domain.strategies.composite_rank import UsedReport


def bar_version_hash(bars: tuple[VersionedDailyBar, ...]) -> str:
    lines = "\n".join(
        f"{item.bar.trading_date.isoformat()}:{item.version}"
        for item in sorted(bars, key=lambda item: item.bar.trading_date)
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def symbol_bar_version_hash(bars: tuple[tuple[str, VersionedDailyBar], ...]) -> str:
    """다종목 해시는 종목코드를 함께 넣는다. 같은 날짜가 종목마다 있기 때문이다."""
    lines = "\n".join(
        f"{symbol}:{item.bar.trading_date.isoformat()}:{item.version}"
        for symbol, item in sorted(bars, key=lambda entry: (entry[0], entry[1].bar.trading_date))
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def action_version_hash(actions: tuple[tuple[date, VersionedCorporateAction], ...]) -> str:
    lines = "\n".join(
        f"{ex_date.isoformat()}:{item.action_key}:{item.version}"
        for ex_date, item in sorted(
            actions,
            key=lambda entry: (entry[0], str(entry[1].action_key)),
        )
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def report_version_hash(reports: tuple[UsedReport, ...]) -> str:
    """종합 순위가 실제로 쓴 사업보고서 계보. 접수번호가 버전을 유일하게 가리킨다."""
    lines = "\n".join(
        f"{item.symbol}:{item.bsns_year}:{item.reprt_code}:{item.fs_div}:{item.rcept_no}"
        for item in sorted(
            reports,
            key=lambda item: (item.symbol, item.bsns_year, item.reprt_code, item.fs_div),
        )
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()
