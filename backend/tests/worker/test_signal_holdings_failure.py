"""신호 후보를 만들 때의 계좌 조회 실패도 사실로 남는다(인계 169번).

ADR-0016 결정 4에 따라 후보는 저장된 스냅샷이 아니라 **방금 조회한 보유**의 차집합으로 만든다.
그 조회는 `OrderPlanner` 밖에 있어서 플래너의 실패 기록 경로를 지나지 않았다. 그 결과 예약 경로의
전송 실패가 `scheduled_job_run.error_code`에만 남고 `api_failure` 이벤트가 되지 않아, 정책 §3의
"외부 API 5분 내 3회 실패" 규칙이 이 호출에는 작동하지 않았다(2026-09-04 실측: `KisTransportError`
4건에 `api_failure` 0건).
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, final

import anyio
import pytest

from auto_stock_trading.adapters.brokers.kis_http import KisTransportError
from auto_stock_trading.worker.execution.planning import fetch_signal_holdings

if TYPE_CHECKING:
    from auto_stock_trading.domain.orders.account import AccountSnapshotObservation

_NOW: Final = datetime(2026, 9, 4, 1, 5, tzinfo=UTC)
_ENVIRONMENT: Final = "paper"


@final
class _RecordingStore:
    def __init__(self) -> None:
        self.failures: list[tuple[str, str]] = []

    async def record_api_failure(
        self,
        environment: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        _ = occurred_at
        self.failures.append((environment, detail))


@final
class _FailingAccounts:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def fetch_balance(self) -> AccountSnapshotObservation:
        raise self._error


def test_a_failed_holdings_fetch_is_recorded_before_it_propagates() -> None:
    store = _RecordingStore()
    accounts = _FailingAccounts(
        KisTransportError("/uapi/domestic-stock/v1/trading/inquire-balance", None)
    )

    async def run() -> None:
        with pytest.raises(KisTransportError):
            _ = await fetch_signal_holdings(accounts, store, _ENVIRONMENT, _NOW)

    anyio.run(run)

    assert store.failures == [(_ENVIRONMENT, "signal_holdings:KisTransportError")]


def test_the_failure_still_propagates_so_the_slot_is_not_reported_as_done() -> None:
    """기록하고 삼키면 그 슬롯이 성공한 것처럼 보인다. 기록한 뒤 그대로 던진다."""
    store = _RecordingStore()
    accounts = _FailingAccounts(RuntimeError("boom"))

    async def run() -> None:
        with pytest.raises(RuntimeError, match="boom"):
            _ = await fetch_signal_holdings(accounts, store, _ENVIRONMENT, _NOW)

    anyio.run(run)

    assert store.failures == [(_ENVIRONMENT, "signal_holdings:RuntimeError")]
