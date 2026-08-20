from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from auto_stock_trading.domain.strategies.momentum import (
    MomentumParameters,
    SymbolSeries,
    momentum_rebalances,
    rebalance_dates,
)

_PARAMS: Final = MomentumParameters(lookback_days=2, holdings=2)
_START: Final = date(2025, 1, 2)


def _dates(count: int, start: date = _START) -> tuple[date, ...]:
    # 달 경계를 포함하도록 실제 달력 날짜를 그대로 쓴다(주말 무관, 거래일 목록 가정).
    return tuple(date.fromordinal(start.toordinal() + offset) for offset in range(count))


def _series(symbol: str, closes: tuple[str, ...], dates: tuple[date, ...]) -> SymbolSeries:
    return SymbolSeries(
        symbol=symbol,
        closes={day: Decimal(value) for day, value in zip(dates, closes, strict=True)},
    )


def test_rebalance_dates_are_the_last_trading_day_of_each_month() -> None:
    dates = (
        date(2025, 1, 30),
        date(2025, 1, 31),
        date(2025, 2, 3),
        date(2025, 2, 27),
        date(2025, 3, 4),
    )

    assert rebalance_dates(dates) == (date(2025, 1, 31), date(2025, 2, 27), date(2025, 3, 4))


def test_top_holdings_are_ranked_by_lookback_return() -> None:
    dates = _dates(4)
    series = (
        _series("000001", ("100", "100", "100", "130"), dates),
        _series("000002", ("100", "100", "100", "120"), dates),
        _series("000003", ("100", "100", "100", "110"), dates),
    )

    ranked = momentum_rebalances(dates[-1:], series, _PARAMS, dates)

    assert [(item.symbol, item.momentum) for item in ranked[0].selected] == [
        ("000001", Decimal("0.30")),
        ("000002", Decimal("0.20")),
    ]


def test_a_tie_is_broken_by_symbol_code_so_runs_reproduce() -> None:
    dates = _dates(4)
    series = (
        _series("000009", ("100", "100", "100", "120"), dates),
        _series("000002", ("100", "100", "100", "120"), dates),
    )

    ranked = momentum_rebalances(dates[-1:], series, MomentumParameters(2, 1), dates)

    assert [item.symbol for item in ranked[0].selected] == ["000002"]


def test_symbols_without_a_full_lookback_window_are_not_candidates() -> None:
    """신규 상장·거래정지로 기준 시점 봉이 없으면 모멘텀을 만들 수 없다."""
    dates = _dates(4)
    complete = _series("000001", ("100", "100", "100", "105"), dates)
    listed_late = SymbolSeries(
        symbol="000002",
        closes={dates[2]: Decimal(100), dates[3]: Decimal(200)},
    )

    ranked = momentum_rebalances(
        dates[-1:], (complete, listed_late), MomentumParameters(2, 2), dates
    )

    assert [item.symbol for item in ranked[0].selected] == ["000001"]


def test_a_missing_bar_on_the_signal_date_excludes_the_symbol() -> None:
    dates = _dates(4)
    halted = SymbolSeries(
        symbol="000002",
        closes={dates[0]: Decimal(100), dates[1]: Decimal(100)},
    )
    complete = _series("000001", ("100", "100", "100", "105"), dates)

    ranked = momentum_rebalances(dates[-1:], (complete, halted), MomentumParameters(2, 2), dates)

    assert [item.symbol for item in ranked[0].selected] == ["000001"]


def test_the_ranking_uses_only_data_up_to_the_signal_date() -> None:
    """접두 시계열만으로 같은 순위가 나와야 한다(미래정보 검사와 같은 성질)."""
    dates = _dates(6)
    series = (
        _series("000001", ("100", "100", "100", "130", "100", "100"), dates),
        _series("000002", ("100", "100", "100", "120", "500", "500"), dates),
    )

    full = momentum_rebalances((dates[3],), series, MomentumParameters(2, 1), dates)
    prefix = momentum_rebalances(
        (dates[3],),
        tuple(
            SymbolSeries(
                symbol=item.symbol,
                closes={day: value for day, value in item.closes.items() if day <= dates[3]},
            )
            for item in series
        ),
        MomentumParameters(2, 1),
        dates,
    )

    assert full == prefix


@pytest.mark.parametrize(("lookback", "holdings"), [(0, 1), (2, 0), (-1, 1)])
def test_invalid_parameters_are_refused(lookback: int, holdings: int) -> None:
    with pytest.raises(ValueError, match="momentum"):
        _ = MomentumParameters(lookback, holdings).validated()


def test_a_signal_date_without_a_full_lookback_window_produces_no_rebalance() -> None:
    """실측 결함: 기준일을 시그널일로 되돌리면 전 종목 모멘텀이 0이 되어 코드순 상위 K가 뽑혔다.

    lookback 구간이 창 안에 없으면 순위를 만들 수 없으므로 그 회차를 만들지 않는다.
    빈 선정으로 회차를 만들면 엔진이 보유 전량을 매도해 버리므로 회차 자체를 건너뛴다.
    """
    dates = _dates(5)
    series = (
        _series("000009", ("100", "100", "100", "100", "150"), dates),
        _series("000002", ("100", "100", "100", "100", "110"), dates),
    )

    early = momentum_rebalances((dates[1],), series, MomentumParameters(4, 1), dates)
    late = momentum_rebalances((dates[4],), series, MomentumParameters(4, 1), dates)

    assert early == ()
    assert [item.symbol for item in late[0].selected] == ["000009"]


def test_the_trading_calendar_is_required_to_locate_the_lookback_basis() -> None:
    dates = _dates(4)
    series = (_series("000001", ("100", "100", "100", "130"), dates),)

    ranked = momentum_rebalances((dates[3],), series, MomentumParameters(2, 1), dates)

    assert ranked[0].selected[0].momentum == Decimal("0.30")
