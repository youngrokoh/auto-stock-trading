from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import final
from uuid import uuid4

import anyio

from auto_stock_trading.application.etf import (
    DistributionYieldUnavailableReason,
    EtfNavSweeper,
    distribution_yield,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    TimePrecision,
    VersionedCorporateAction,
)
from auto_stock_trading.domain.market_data.etf import (
    EtfMasterBundle,
    EtfNavObservation,
    EtfNavSnapshot,
    VersionedEtfProfile,
)
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse

_NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


def _snapshot(price: str = "110060") -> EtfNavSnapshot:
    return EtfNavSnapshot(
        symbol="069500",
        price=Decimal(price),
        change_percent=Decimal("0.00"),
        volume=495,
        previous_volume=17088038,
        nav=Decimal("110371.90"),
        divergence_rate=Decimal("-0.28"),
        tracking_error=Decimal("0.39"),
        tracking_multiple=Decimal("1.00"),
        net_asset_total=260643,
        listed_shares=236150000,
        manager="삼성자산운용(ETF)",
        index_name="KOSPI200",
        listing_date=date(2002, 10, 14),
        currency="KRW",
        source="KIS",
        as_of=_NOW,
        received_at=_NOW,
    )


def _distribution(
    ex_date: date | None,
    amount: str | None,
    *,
    action_type: CorporateActionType = CorporateActionType.ETF_DISTRIBUTION,
    lifecycle: CorporateActionLifecycle = CorporateActionLifecycle.CONFIRMED,
) -> VersionedCorporateAction:
    action = CorporateAction(
        action_type=action_type,
        lifecycle=lifecycle,
        quality=CorporateActionQuality.VERIFIED,
        announced_at=None,
        announcement_date=date(2026, 7, 1),
        time_precision=TimePrecision.DATE,
        ex_date=ex_date,
        effective_date=None,
        record_date=None,
        payment_date=None,
        share_multiplier=None,
        cash_amount=None if amount is None else Decimal(amount),
        currency="KRW",
        subscription_price=None,
        related_instrument_id=None,
        source="KODEX",
        source_event_id=f"kodex:{ex_date}",
        source_reference="fixture",
        available_at=_NOW,
        received_at=_NOW,
    )
    return VersionedCorporateAction(
        action=action,
        corporate_action_id=uuid4(),
        action_key=uuid4(),
        version=1,
        valid_from=_NOW,
        superseded_at=None,
    )


def test_distribution_yield_sums_only_recent_confirmed_distributions() -> None:
    actions = (
        _distribution(date(2026, 7, 30), "183"),
        _distribution(date(2026, 4, 29), "175"),
        _distribution(date(2026, 1, 29), "180"),
        _distribution(date(2025, 10, 30), "170"),
        # 12개월 창 밖
        _distribution(date(2025, 7, 30), "160"),
        # 취소·다른 유형·락일 없음은 제외
        _distribution(date(2026, 6, 1), "999", lifecycle=CorporateActionLifecycle.CANCELLED),
        _distribution(date(2026, 6, 1), "999", action_type=CorporateActionType.CASH_DIVIDEND),
        _distribution(None, "999"),
    )

    result = distribution_yield(actions, _snapshot())

    assert result.distribution_total == Decimal(708)
    assert result.distribution_count == 4
    # 708 ÷ 110060 × 100 = 0.6433...
    assert result.value == Decimal("0.64")
    assert result.window_end == date(2026, 8, 18)
    assert "12개월" in result.formula


def test_distribution_yield_fails_closed_without_snapshot_or_history() -> None:
    no_snapshot = distribution_yield((_distribution(date(2026, 7, 30), "183"),), None)
    no_history = distribution_yield((), _snapshot())

    assert no_snapshot.value is None
    assert no_snapshot.unavailable_reason is DistributionYieldUnavailableReason.MISSING_SNAPSHOT
    assert no_history.value is None
    assert no_history.unavailable_reason is DistributionYieldUnavailableReason.MISSING_DISTRIBUTIONS


def _profile(symbol: str) -> VersionedEtfProfile:
    return VersionedEtfProfile(
        symbol=symbol,
        isin=f"KR7{symbol}000",
        name=f"ETF {symbol}",
        source="KIS_MASTER",
        received_at=_NOW,
        version=1,
        valid_from=_NOW,
        superseded_at=None,
    )


@final
class FlakyNavSource:
    async def fetch_snapshot(self, symbol: str) -> EtfNavObservation:
        if symbol == "999999":
            msg = "boom"
            raise RuntimeError(msg)
        raw = RawBrokerResponse(
            operation=BrokerOperation.ETF_NAV,
            endpoint="/uapi/etfetn/v1/quotations/inquire-price",
            request_fingerprint=f"etf_nav:{symbol}",
            received_at=_NOW,
            payload_json="{}",
        )
        return EtfNavObservation(snapshot=_snapshot(), raw=raw)

    async def close(self) -> None:
        return None


@final
@dataclass
class RecordingEtfStore:
    saved: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    async def mark_started(self, operation: str, key: str, started_at: datetime) -> None:
        _ = started_at
        self.events.append(f"started:{operation}:{key}")

    async def mark_succeeded(self, operation: str, key: str, completed_at: datetime) -> None:
        _ = completed_at
        self.events.append(f"succeeded:{operation}:{key}")

    async def mark_failed(
        self,
        operation: str,
        key: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        _ = (failed_at, error_message)
        self.events.append(f"failed:{operation}:{key}:{error_code}")

    async def save_master_bundle(self, bundle: EtfMasterBundle) -> int:
        _ = bundle
        return 0

    async def save_nav_observation(self, observation: EtfNavObservation) -> None:
        self.saved.append(observation.snapshot.symbol)

    async def profiles(self) -> tuple[VersionedEtfProfile, ...]:
        return (_profile("069500"), _profile("999999"), _profile("102110"))

    async def close(self) -> None:
        return None


def test_nav_sweep_continues_after_individual_failures_and_reports_counts() -> None:
    async def run() -> None:
        store = RecordingEtfStore()
        sweeper = EtfNavSweeper(FlakyNavSource(), store)

        result = await sweeper.collect(_NOW)

        assert result.collected == 2
        assert result.failed == 1
        assert store.saved == ["069500", "069500"]
        assert store.events[0] == "started:etf_nav:ETF"
        assert store.events[-1] == "failed:etf_nav:ETF:partial_failure"

    anyio.run(run)
