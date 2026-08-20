from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, final

import anyio

from auto_stock_trading.application.stock_universe import (
    QuoteSweeper,
    StockUniverseCollector,
)
from auto_stock_trading.domain.market_data.listed_shares import ListedShareCount
from auto_stock_trading.domain.market_data.models import (
    BrokerOperation,
    InstrumentTarget,
    Quote,
    QuoteSnapshotObservation,
    RawBrokerResponse,
)
from auto_stock_trading.domain.market_data.stocks import StockMasterBundle, StockProfile

_NOW: Final = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
_PRICE: Final = Decimal(250_000)


def _raw(fingerprint: str) -> RawBrokerResponse:
    return RawBrokerResponse(
        operation=BrokerOperation.STOCK_MASTER,
        endpoint="/fixture",
        request_fingerprint=fingerprint,
        received_at=_NOW,
        payload_json="{}",
    )


def _bundle(symbols: tuple[str, ...]) -> StockMasterBundle:
    return StockMasterBundle(
        profiles=tuple(
            StockProfile(
                symbol=symbol,
                isin=f"KR7{symbol}003",
                name=f"종목{symbol}",
                sector_code="5",
                source="KIS_MASTER",
                received_at=_NOW,
            )
            for symbol in symbols
        ),
        raw=_raw("stock_master:kospi"),
        collected_at=_NOW,
    )


@final
@dataclass
class FakeMasterSource:
    symbols: tuple[str, ...] = ("005930", "035420")
    fails: bool = False

    async def fetch_master(self, now: datetime) -> StockMasterBundle:
        assert now is not None
        if self.fails:
            raise TimeoutError
        return _bundle(self.symbols)

    async def close(self) -> None:
        return None


@final
@dataclass
class FakeQuoteSource:
    failing: tuple[str, ...] = ()
    hanging: tuple[str, ...] = ()
    requested: list[str] = field(default_factory=list)

    async def fetch_quote_snapshot(self, target: InstrumentTarget) -> QuoteSnapshotObservation:
        self.requested.append(target.symbol)
        if target.symbol in self.hanging:
            await anyio.sleep(30)
        if target.symbol in self.failing:
            raise TimeoutError
        return QuoteSnapshotObservation(
            quote=Quote(
                symbol=target.symbol,
                price=_PRICE,
                open_price=_PRICE,
                high_price=_PRICE,
                low_price=_PRICE,
                previous_close=_PRICE,
                change=Decimal(0),
                change_percent=Decimal(0),
                volume=1,
                trading_value=Decimal(1),
                currency="KRW",
                source="KIS",
                as_of=_NOW,
                received_at=_NOW,
            ),
            listed_shares=ListedShareCount(
                symbol=target.symbol,
                share_count=5_969_782_550,
                source="KIS",
                as_of=_NOW,
                received_at=_NOW,
            ),
            raw=_raw(f"quote:{target.symbol}"),
        )

    async def close(self) -> None:
        return None


@final
@dataclass
class FakeStore:
    symbols: tuple[str, ...] = ("005930", "035420")
    saved_bundles: list[int] = field(default_factory=list)
    saved_quotes: list[str] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    succeeded: list[str] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)

    async def mark_started(self, operation: str, key: str, started_at: datetime) -> None:
        assert started_at is not None
        self.started.append(f"{operation}:{key}")

    async def mark_succeeded(self, operation: str, key: str, completed_at: datetime) -> None:
        assert completed_at is not None
        self.succeeded.append(f"{operation}:{key}")

    async def mark_failed(
        self,
        operation: str,
        key: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        assert failed_at is not None
        # 메시지는 비어 있을 수 있다(`str(TimeoutError())`). 사유는 코드가 담는다.
        assert isinstance(error_message, str)
        self.failures.append((f"{operation}:{key}", error_code))

    async def save_master_bundle(self, bundle: StockMasterBundle) -> int:
        self.saved_bundles.append(len(bundle.profiles))
        return len(bundle.profiles)

    async def save_quote_snapshot(self, observation: QuoteSnapshotObservation) -> None:
        self.saved_quotes.append(observation.quote.symbol)

    async def universe_symbols(self) -> tuple[str, ...]:
        return self.symbols

    async def close(self) -> None:
        return None


def test_master_collection_reports_observed_and_saved_counts() -> None:
    async def run() -> None:
        store = FakeStore()
        collector = StockUniverseCollector(source=FakeMasterSource(), store=store)

        result = await collector.collect(_NOW)

        assert (result.observed, result.saved) == (2, 2)
        assert store.started == ["stock_master:KOSPI200"]
        assert store.succeeded == ["stock_master:KOSPI200"]
        assert store.failures == []

    anyio.run(run)


def test_master_collection_records_the_failure_and_reraises() -> None:
    async def run() -> None:
        store = FakeStore()
        collector = StockUniverseCollector(source=FakeMasterSource(fails=True), store=store)

        try:
            _ = await collector.collect(_NOW)
        except TimeoutError:
            pass
        else:
            raise AssertionError

        assert store.failures == [("stock_master:KOSPI200", "TimeoutError")]
        assert store.succeeded == []

    anyio.run(run)


def test_quote_sweep_covers_the_stored_universe() -> None:
    async def run() -> None:
        store = FakeStore()
        source = FakeQuoteSource()

        result = await QuoteSweeper(source=source, store=store).collect(_NOW)

        assert (result.collected, result.failed) == (2, 0)
        assert source.requested == ["005930", "035420"]
        assert store.saved_quotes == ["005930", "035420"]
        assert store.succeeded == ["universe_quote:KOSPI200"]

    anyio.run(run)


def test_a_single_symbol_failure_does_not_stop_the_sweep() -> None:
    async def run() -> None:
        store = FakeStore(symbols=("005930", "035420", "000660"))
        source = FakeQuoteSource(failing=("035420",))

        result = await QuoteSweeper(source=source, store=store).collect(_NOW)

        assert (result.collected, result.failed) == (2, 1)
        assert store.saved_quotes == ["005930", "000660"]
        assert store.failures == [("universe_quote:KOSPI200", "partial_failure")]
        assert store.succeeded == []

    anyio.run(run)


def test_a_hung_symbol_request_is_abandoned_so_the_sweep_finishes() -> None:
    """실측 결함: 한 종목 요청이 응답 없이 매달리면 스윕 전체가 멈췄다.

    HTTP 읽기 타임아웃이 걸리지 않는 경우가 있으므로 종목당 상한을 유스케이스가 강제한다.
    """

    async def run() -> None:
        store = FakeStore(symbols=("005930", "035420", "000660"))
        source = FakeQuoteSource(hanging=("035420",))

        result = await QuoteSweeper(
            source=source,
            store=store,
            symbol_timeout_seconds=0.05,
        ).collect(_NOW)

        assert (result.collected, result.failed) == (2, 1)
        assert store.saved_quotes == ["005930", "000660"]
        assert store.failures == [("universe_quote:KOSPI200", "partial_failure")]

    anyio.run(run)
