"""모의투자 주문 제출·체결 동기화·취소 CLI. 사람이 실행할 때만 증권사에 주문을 보낸다."""

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

import anyio

from auto_stock_trading.adapters.brokers.kis_coordination import kis_coordination_scope
from auto_stock_trading.adapters.brokers.kis_coordination_valkey import (
    ValkeyKisRequestCoordinator,
)
from auto_stock_trading.adapters.brokers.kis_http import KisHttpClient, create_kis_http_client
from auto_stock_trading.adapters.brokers.kis_orders import KisOrderAdapter
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.trading_attestation_store import (
    PostgresAttestationStore,
)
from auto_stock_trading.adapters.database.trading_notification_store import (
    PostgresNotificationStore,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.trading.attestation import (
    AttestationInput,
    OrderAttestor,
)
from auto_stock_trading.application.trading.planning import AutomationTransition
from auto_stock_trading.application.trading.submission import (
    OrderSubmitter,
    SubmissionInput,
)
from auto_stock_trading.domain.orders.models import AutomationState, OrderState
from auto_stock_trading.domain.risk.limits import seoul_trading_date
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker.kis_credentials import load_kis_account, load_kis_credentials

_EMERGENCY_REASON: Final = "EMERGENCY_STOP"
_PAPER_ONLY: Final = "order submission is allowed in the paper environment only"
_WITHDRAW_REASON: Final = "USER_COMMAND"
_WITHDRAW_NEEDS_PLAN: Final = "--withdraw requires --plan-id"
_ATTEST_NEEDS: Final = "--attest requires {}"


class Arguments(argparse.Namespace):
    plan_id: str | None = None
    submit: bool = False
    sync: bool = False
    emergency_stop: bool = False
    withdraw: bool = False
    attest: bool = False
    broker_order_id: str | None = None
    state: str | None = None
    quantity: int | None = None
    price: str | None = None
    operator: str | None = None
    evidence: str | None = None


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


@dataclass(frozen=True, slots=True)
class _Collaborators:
    """CLI 한 번 실행에 쓰는 어댑터 묶음. 종료 시 모두 닫는다."""

    calendar: PostgresMarketCalendarRepository
    store: PostgresTradingStore
    notifications: PostgresNotificationStore
    broker: KisOrderAdapter
    submitter: OrderSubmitter

    async def close(self) -> None:
        await self.broker.close()
        await self.calendar.close()
        await self.notifications.close()
        await self.store.close()


def _collaborators(settings: Settings) -> _Collaborators:
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    store = PostgresTradingStore.from_url(database_url)
    notifications = PostgresNotificationStore.from_url(database_url)
    broker = KisOrderAdapter(_http_client(settings), load_kis_account(settings), paper=True)
    return _Collaborators(
        calendar=calendar,
        store=store,
        notifications=notifications,
        broker=broker,
        submitter=OrderSubmitter(
            calendar=calendar,
            broker=broker,
            store=store,
            listener=notifications,
        ),
    )


async def submit_orders(arguments: Arguments) -> str:
    settings = _paper_settings()
    collaborators = _collaborators(settings)
    submitter = collaborators.submitter
    request = SubmissionInput(
        environment=settings.kis_environment.value,
        plan_id=None if arguments.plan_id is None else UUID(arguments.plan_id),
    )
    try:
        result = await submitter.submit(request, datetime.now(UTC))
    finally:
        await collaborators.close()
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


async def attest_order_state(arguments: Arguments) -> str:
    """사람이 확인한 사실로 주문을 종결한다(ADR-0010). 증권사 호출은 없다."""
    settings = _paper_settings()
    missing = [
        name
        for name, value in (
            ("--broker-order-id", arguments.broker_order_id),
            ("--state", arguments.state),
            ("--quantity", arguments.quantity),
            ("--operator", arguments.operator),
            ("--evidence", arguments.evidence),
        )
        if value is None
    ]
    if missing:
        raise RuntimeError(_ATTEST_NEEDS.format(", ".join(missing)))
    store = PostgresAttestationStore.from_url(settings.database_url.get_secret_value())
    request = AttestationInput(
        environment=settings.kis_environment.value,
        broker_order_id=arguments.broker_order_id or "",
        state=OrderState(arguments.state),
        filled_quantity=arguments.quantity or 0,
        average_fill_price=None if arguments.price is None else Decimal(arguments.price),
        operator=arguments.operator or "",
        evidence=arguments.evidence or "",
    )
    try:
        result = await OrderAttestor(store=store).attest(request, datetime.now(UTC))
    finally:
        await store.close()
    if not result.applied:
        return f"refused reason={result.reason}"
    state = result.state.value if result.state is not None else "-"
    return f"attested order={result.client_order_id} state={state}"


async def synchronize_fills() -> str:
    settings = _paper_settings()
    collaborators = _collaborators(settings)
    try:
        summary = await collaborators.submitter.synchronize(
            settings.kis_environment.value,
            datetime.now(UTC),
        )
    finally:
        await collaborators.close()
    updated = ",".join(f"{order}:{state.value}" for order, state in summary.updated)
    problems = ",".join(f"{order}:{problem.value}" for order, problem in summary.problems)
    return (
        f"updated={len(summary.updated)} problems={len(summary.problems)} "
        f"paused={summary.paused} states={updated or '-'} reasons={problems or '-'}"
    )


async def emergency_stop() -> str:
    """정책 §6대로 비상정지 후 미체결 주문 취소를 시도한다. 보유는 청산하지 않는다."""
    settings = _paper_settings()
    collaborators = _collaborators(settings)
    now = datetime.now(UTC)
    environment = settings.kis_environment.value
    try:
        record = await collaborators.store.transition_automation(
            AutomationTransition(
                environment=environment,
                requested=AutomationState.EMERGENCY_STOP,
                reason_code=_EMERGENCY_REASON,
                occurred_at=now,
                trading_date=seoul_trading_date(now),
            )
        )
        summary = await collaborators.submitter.cancel_open_orders(
            environment,
            now,
            _EMERGENCY_REASON,
        )
    finally:
        await collaborators.close()
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
    _ = parser.add_argument("--attest", action="store_true")
    _ = parser.add_argument("--broker-order-id")
    _ = parser.add_argument(
        "--state",
        choices=(
            OrderState.FILLED.value,
            OrderState.PARTIALLY_FILLED.value,
            OrderState.CANCELED.value,
        ),
    )
    _ = parser.add_argument("--quantity", type=int)
    _ = parser.add_argument("--price")
    _ = parser.add_argument("--operator")
    _ = parser.add_argument("--evidence")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.attest:
        print(anyio.run(attest_order_state, arguments))  # noqa: T201
        return
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
        parser.error("--submit, --sync, --withdraw, --attest, --emergency-stop 중 하나가 필요하다")


if __name__ == "__main__":
    main()
