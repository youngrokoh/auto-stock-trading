"""가치·수익성·모멘텀 종합 순위(백테스트 계약 v3). 순수 함수이며 저장·조회를 하지 않는다.

재무 지표(ROE·기본주당이익)의 정의는 재무 지표 정의 계약이 갖는다. 이 모듈은 시점 정합
선택과 요인 종합만 한다.
"""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.strategies.ranking import (
    RankedSymbol,
    Rebalance,
    SymbolSeries,
    descending_ranks,
    quantized_score,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from decimal import Decimal

_RECEIPT_DATE_LENGTH: Final = 8
_RECEIPT_LENGTH: Final = 14
_FACTORS: Final = 3


@dataclass(frozen=True, slots=True)
class CompositeParameters:
    lookback_days: int
    holdings: int

    def validated(self) -> CompositeParameters:
        if self.lookback_days < 1:
            message = "composite lookback_days must be at least 1"
            raise ValueError(message)
        if self.holdings < 1:
            message = "composite holdings must be at least 1"
            raise ValueError(message)
        return self


@dataclass(frozen=True, slots=True)
class AnnualFact:
    """연간 사업보고서 하나에서 나온 시점 정합 재무 사실."""

    bsns_year: int
    reprt_code: str
    fs_div: str
    rcept_no: str
    filed_on: date
    roe: Decimal | None
    eps: Decimal | None


@dataclass(frozen=True, slots=True)
class SymbolFundamentals:
    symbol: str
    facts: tuple[AnnualFact, ...]


@dataclass(frozen=True, slots=True)
class UsedReport:
    symbol: str
    bsns_year: int
    reprt_code: str
    fs_div: str
    rcept_no: str


@dataclass(frozen=True, slots=True)
class CompositeResult:
    rebalances: tuple[Rebalance, ...]
    # 순위를 결정한 모든 보고서. 선정되지 않은 후보의 보고서도 결과를 바꾸므로 계보에 남는다.
    used_reports: tuple[UsedReport, ...]


def disclosure_filed_on(rcept_no: str) -> date:
    """접수번호 앞 8자리가 접수일이다. 형식이 다르면 추측하지 않고 거부한다."""
    if len(rcept_no) != _RECEIPT_LENGTH or not rcept_no.isdigit():
        message = f"malformed DART receipt number: {rcept_no}"
        raise ValueError(message)
    return date.fromisoformat(f"{rcept_no[0:4]}-{rcept_no[4:6]}-{rcept_no[6:_RECEIPT_DATE_LENGTH]}")


def point_in_time_fact(facts: Sequence[AnnualFact], signal_date: date) -> AnnualFact | None:
    """시그널일에 알 수 있었던 보고서.

    사용 조건은 접수일 다음 거래일이 시그널일 이하인 것이다. 시그널일은 거래일이므로
    `접수일 < 시그널일`과 같다. 접수일 당일은 공시가 장중·장후에 나올 수 있어 쓰지 않는다.
    """
    usable = [fact for fact in facts if fact.filed_on < signal_date]
    if not usable:
        return None
    return max(usable, key=lambda fact: (fact.bsns_year, fact.rcept_no))


def _momentum(series: SymbolSeries, signal_date: date, basis_date: date) -> Decimal | None:
    current = series.closes.get(signal_date)
    basis = series.closes.get(basis_date)
    if current is None or basis is None or basis <= 0:
        return None
    return current / basis - 1


@dataclass(frozen=True, slots=True)
class _Candidate:
    symbol: str
    earnings_yield: Decimal
    roe: Decimal
    momentum: Decimal
    report: UsedReport


def _candidate(
    series: SymbolSeries,
    fact: AnnualFact | None,
    signal_date: date,
    basis_date: date,
) -> _Candidate | None:
    """요인 하나라도 없으면 후보가 아니다(계약 v3 결측 처리)."""
    if fact is None or fact.roe is None or fact.eps is None:
        return None
    momentum = _momentum(series, signal_date, basis_date)
    close = series.closes.get(signal_date)
    if momentum is None or close is None or close <= 0:
        return None
    return _Candidate(
        symbol=series.symbol,
        earnings_yield=fact.eps / close,
        roe=fact.roe,
        momentum=momentum,
        report=UsedReport(
            symbol=series.symbol,
            bsns_year=fact.bsns_year,
            reprt_code=fact.reprt_code,
            fs_div=fact.fs_div,
            rcept_no=fact.rcept_no,
        ),
    )


def _selected(candidates: Sequence[_Candidate], holdings: int) -> tuple[RankedSymbol, ...]:
    value_ranks = descending_ranks({item.symbol: item.earnings_yield for item in candidates})
    quality_ranks = descending_ranks({item.symbol: item.roe for item in candidates})
    momentum_ranks = descending_ranks({item.symbol: item.momentum for item in candidates})
    scored = [
        RankedSymbol(
            symbol=item.symbol,
            score=quantized_score(
                (
                    value_ranks[item.symbol]
                    + quality_ranks[item.symbol]
                    + momentum_ranks[item.symbol]
                )
                / _FACTORS
            ),
        )
        for item in candidates
    ]
    scored.sort(key=lambda item: (item.score, item.symbol))
    return tuple(scored[:holdings])


def composite_rebalances(
    signal_dates: Sequence[date],
    universe: Sequence[SymbolSeries],
    fundamentals: Sequence[SymbolFundamentals],
    parameters: CompositeParameters,
    trading_dates: Sequence[date],
) -> CompositeResult:
    """회차별 선정 종목과 사용한 보고서. 후보가 없는 회차는 만들지 않는다."""
    settings = parameters.validated()
    calendar = tuple(trading_dates)
    index_of = {day: index for index, day in enumerate(calendar)}
    facts_of = {item.symbol: item.facts for item in fundamentals}
    rebalances: list[Rebalance] = []
    used: dict[tuple[str, int, str, str, str], UsedReport] = {}
    for signal_date in signal_dates:
        position = index_of.get(signal_date)
        if position is None:
            continue
        basis_index = position - settings.lookback_days
        if basis_index < 0:
            continue
        basis_date = calendar[basis_index]
        candidates = [
            candidate
            for series in universe
            if (
                candidate := _candidate(
                    series,
                    point_in_time_fact(facts_of.get(series.symbol, ()), signal_date),
                    signal_date,
                    basis_date,
                )
            )
            is not None
        ]
        if not candidates:
            continue
        for item in candidates:
            report = item.report
            used[
                (
                    report.symbol,
                    report.bsns_year,
                    report.reprt_code,
                    report.fs_div,
                    report.rcept_no,
                )
            ] = report
        rebalances.append(
            Rebalance(
                signal_date=signal_date,
                selected=_selected(candidates, settings.holdings),
            )
        )
    return CompositeResult(
        rebalances=tuple(rebalances),
        used_reports=tuple(used[key] for key in sorted(used)),
    )
