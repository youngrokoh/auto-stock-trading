"""실주문 신호 생성 CLI(ADR-0016).

`--generate`는 확정 봉으로 목표를 계산해 저장한다. **증권사 자격증명이 필요 없다** — 저장된 확정
봉만 읽는다. `--status`는 저장된 최신 목표를 출력한다.

신호가 저장돼 있어도 자동매매가 `RUNNING`이 아니면 주문은 나가지 않는다(정책 §6). 이 명령은 자동매매
상태를 바꾸지 않는다.
"""

import argparse
from datetime import UTC, datetime
from typing import Final

import anyio

from auto_stock_trading.adapters.database.live_signal_store import PostgresLiveSignalStore
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.application.trading.signals import (
    STRATEGY_NAME,
    LiveSignalGenerator,
)
from auto_stock_trading.domain.strategies.etf_allocation import EtfAllocationParameters
from auto_stock_trading.settings.runtime import KisEnvironment, Settings

# 백테스트 실측과 같은 값이다. 다르면 검증한 전략과 주문하는 전략이 갈라진다.
_LOOKBACK_DAYS: Final = 250
_HOLDINGS: Final = 2
_PAPER_ONLY: Final = "live signals are generated in the paper environment only"


class Arguments(argparse.Namespace):
    generate: bool = False
    status: bool = False


async def generate_signal() -> str:
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        raise RuntimeError(_PAPER_ONLY)
    database_url = settings.database_url.get_secret_value()
    bars = PostgresMarketDataRepository.from_url(database_url)
    store = PostgresLiveSignalStore.from_url(database_url)
    generator = LiveSignalGenerator(
        bars=bars,
        parameters=EtfAllocationParameters(
            lookback_days=_LOOKBACK_DAYS,
            holdings=_HOLDINGS,
        ),
    )
    now = datetime.now(UTC)
    try:
        outcome = await generator.generate(now)
        if outcome.signal is None:
            return f"no_signal reason={outcome.reason}"
        stored = await store.save(settings.kis_environment.value, outcome.signal, now)
    finally:
        await store.close()
        await bars.close()
    signal = outcome.signal
    targets = ",".join(f"{item.symbol}:{item.score}" for item in signal.targets)
    return (
        f"{'stored' if stored else 'exists'} basis_date={signal.basis_date} "
        f"rebalance_date={signal.rebalance_date} targets={targets}"
    )


async def signal_status() -> str:
    settings = Settings()
    store = PostgresLiveSignalStore.from_url(settings.database_url.get_secret_value())
    try:
        latest = await store.latest_targets(settings.kis_environment.value, STRATEGY_NAME)
    finally:
        await store.close()
    if latest is None:
        return "no_signal"
    symbols = ",".join(item.symbol for item in latest.targets)
    return (
        f"basis_date={latest.basis_date} rebalance_date={latest.rebalance_date} targets={symbols}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="실주문 신호 생성 (주문은 하지 않음)")
    _ = parser.add_argument("--generate", action="store_true")
    _ = parser.add_argument("--status", action="store_true")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.generate:
        print(anyio.run(generate_signal))  # noqa: T201
        return
    if arguments.status:
        print(anyio.run(signal_status))  # noqa: T201
        return
    parser.error("--generate 또는 --status 중 하나가 필요하다")


if __name__ == "__main__":
    main()
