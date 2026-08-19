"""모의투자 주문 제출·체결 동기화·취소 CLI. 사람이 실행할 때만 증권사에 주문을 보낸다."""

import argparse
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import anyio

from auto_stock_trading.adapters.brokers.kis_coordination import (
    ValkeyKisRequestCoordinator,
    kis_coordination_scope,
)
from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient, create_kis_http_client
from auto_stock_trading.adapters.brokers.kis_orders import KisOrderAdapter
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.trading.planning import AutomationTransition
from auto_stock_trading.application.trading.submission import (
    OrderSubmitter,
    SubmissionInput,
)
from auto_stock_trading.domain.orders.models import AutomationState
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker.kis_credentials import load_kis_account, load_kis_credentials

_EMERGENCY_REASON: Final = "EMERGENCY_STOP"
_PAPER_ONLY: Final = "order submission is allowed in the paper environment only"
_WITHDRAW_REASON: Final = "USER_COMMAND"
_WITHDRAW_NEEDS_PLAN: Final = "--withdraw requires --plan-id"


class Arguments(argparse.Namespace):
    plan_id: str | None = None
    submit: bool = False
    sync: bool = False
    emergency_stop: bool = False
    withdraw: bool = False


def _http_client(settings: Settings) -> KisHttpClient:
    credentials = load_kis_credentials(settings)
    return KisHttpClient(
        create_kis_http_client(settings.kis_base_url),
        credentials,
        ValkeyKisRequestCoordinator.from_url(
            settings.valkey_url.get_secret_value(),
            kis_coordination_scope(
                settings.kis_environment.value,
                credentials.app_key,
                credentials.app_secret,
            ),
        ),
    )


def _paper_settings() -> Settings:
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        raise RuntimeError(_PAPER_ONLY)
    return settings


async def submit_orders(arguments: Arguments) -> str:
    settings = _paper_settings()
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    store = PostgresTradingStore.from_url(database_url)
    broker = KisOrderAdapter(_http_client(settings), load_kis_account(settings), paper=True)
    submitter = OrderSubmitter(calendar=calendar, broker=broker, store=store)
    request = SubmissionInput(
        environment=settings.kis_environment.value,
        plan_id=None if arguments.plan_id is None else UUID(arguments.plan_id),
    )
    try:
        result = await submitter.submit(request, datetime.now(UTC))
    finally:
        await broker.close()
        await calendar.close()
        await store.close()
    if result.block_code is not None:
        return f"blocked block_code={result.block_code} submitted=0"
    rejected = ",".join(f"{order}:{code}" for order, code in result.rejected)
    return (
        f"submitted={len(result.submitted)} rejected={len(result.rejected)} "
        f"orders={','.join(result.submitted) or '-'} reasons={rejected or '-'}"
    )


async def withdraw_plan(arguments: Arguments) -> str:
    """제출 전 계획 주문을 철회한다. 증권사 호출 없이 내부 상태만 종결한다."""
    settings = _paper_settings()
    if arguments.plan_id is None:
        raise RuntimeError(_WITHDRAW_NEEDS_PLAN)
    store = PostgresTradingStore.from_url(settings.database_url.get_secret_value())
    try:
        withdrawn = await store.withdraw_planned_orders(
            UUID(arguments.plan_id),
            _WITHDRAW_REASON,
            datetime.now(UTC),
        )
    finally:
        await store.close()
    return f"withdrawn={withdrawn} plan_id={arguments.plan_id}"


async def synchronize_fills() -> str:
    settings = _paper_settings()
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    store = PostgresTradingStore.from_url(database_url)
    broker = KisOrderAdapter(_http_client(settings), load_kis_account(settings), paper=True)
    submitter = OrderSubmitter(calendar=calendar, broker=broker, store=store)
    try:
        summary = await submitter.synchronize(settings.kis_environment.value, datetime.now(UTC))
    finally:
        await broker.close()
        await calendar.close()
        await store.close()
    updated = ",".join(f"{order}:{state.value}" for order, state in summary.updated)
    problems = ",".join(f"{order}:{problem.value}" for order, problem in summary.problems)
    return (
        f"updated={len(summary.updated)} problems={len(summary.problems)} "
        f"paused={summary.paused} states={updated or '-'} reasons={problems or '-'}"
    )


async def emergency_stop() -> str:
    """정책 §6대로 비상정지 후 미체결 주문 취소를 시도한다. 보유는 청산하지 않는다."""
    settings = _paper_settings()
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    store = PostgresTradingStore.from_url(database_url)
    broker = KisOrderAdapter(_http_client(settings), load_kis_account(settings), paper=True)
    submitter = OrderSubmitter(calendar=calendar, broker=broker, store=store)
    now = datetime.now(UTC)
    environment = settings.kis_environment.value
    try:
        record = await store.transition_automation(
            AutomationTransition(
                environment=environment,
                requested=AutomationState.EMERGENCY_STOP,
                reason_code=_EMERGENCY_REASON,
                occurred_at=now,
                trading_date=now.date(),
            )
        )
        summary = await submitter.cancel_open_orders(environment, now, _EMERGENCY_REASON)
    finally:
        await broker.close()
        await calendar.close()
        await store.close()
    failed = ",".join(f"{order}:{code}" for order, code in summary.failed)
    return (
        f"state={record.state.value} cancel_requested={len(summary.requested)} "
        f"cancel_failed={len(summary.failed)} reasons={failed or '-'}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="모의투자 주문 제출·체결 동기화·비상정지 (실전 환경에서는 거부)",
    )
    _ = parser.add_argument("--plan-id")
    _ = parser.add_argument("--submit", action="store_true")
    _ = parser.add_argument("--sync", action="store_true")
    _ = parser.add_argument("--emergency-stop", action="store_true")
    _ = parser.add_argument("--withdraw", action="store_true")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.emergency_stop:
        print(anyio.run(emergency_stop))  # noqa: T201
        return
    if arguments.withdraw:
        print(anyio.run(withdraw_plan, arguments))  # noqa: T201
        return
    if arguments.submit:
        print(anyio.run(submit_orders, arguments))  # noqa: T201
    if arguments.sync:
        print(anyio.run(synchronize_fills))  # noqa: T201
    if not arguments.submit and not arguments.sync:
        parser.error("--submit, --sync, --withdraw, --emergency-stop 중 하나가 필요하다")


if __name__ == "__main__":
    main()
