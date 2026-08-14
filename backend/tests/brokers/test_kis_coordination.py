from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import pytest
from pydantic import SecretStr
from redis.asyncio import Redis

from auto_stock_trading.adapters.brokers.kis_coordination import (
    KisAccessToken,
    KisCoordinationConfig,
    KisCoordinationError,
    ValkeyKisRequestCoordinator,
    kis_coordination_scope,
)
from auto_stock_trading.settings.runtime import Settings


def test_coordination_scope_separates_environments_without_exposing_credentials() -> None:
    app_key = SecretStr("fixture-app-key")
    app_secret = SecretStr("fixture-app-secret")

    paper_scope = kis_coordination_scope("paper", app_key, app_secret)
    live_scope = kis_coordination_scope("live", app_key, app_secret)

    assert paper_scope != live_scope
    assert "fixture" not in paper_scope
    assert len(paper_scope) == 64


def test_access_token_uses_the_expiry_safety_window() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    token = KisAccessToken(SecretStr("fixture-token"), now + timedelta(seconds=60))

    assert not token.is_valid_at(now, safety_seconds=60)
    assert token.is_valid_at(now, safety_seconds=59)


def test_valkey_coordinators_issue_one_shared_token() -> None:
    async def run() -> None:
        settings = Settings()
        scope = uuid4().hex
        config = KisCoordinationConfig(
            minimum_interval_seconds=0.01,
            token_lock_seconds=2,
            wait_timeout_seconds=2,
            poll_interval_seconds=0.01,
        )
        first = ValkeyKisRequestCoordinator.from_url(
            settings.valkey_url.get_secret_value(), scope, config
        )
        second = ValkeyKisRequestCoordinator.from_url(
            settings.valkey_url.get_secret_value(), scope, config
        )
        issued = 0
        tokens: list[str] = []

        async def issue_token() -> KisAccessToken:
            nonlocal issued
            issued += 1
            await anyio.sleep(0.05)
            return KisAccessToken(
                SecretStr("shared-fixture-token"),
                datetime.now(UTC) + timedelta(seconds=65),
            )

        async def collect_token(coordinator: ValkeyKisRequestCoordinator) -> None:
            token = await coordinator.token(issue_token)
            tokens.append(token.get_secret_value())

        try:
            async with anyio.create_task_group() as task_group:
                _ = task_group.start_soon(collect_token, first)
                _ = task_group.start_soon(collect_token, second)
        finally:
            await first.close()
            await second.close()

        assert issued == 1
        assert tokens == ["shared-fixture-token", "shared-fixture-token"]

    anyio.run(run)


def test_valkey_coordinators_share_the_request_interval() -> None:
    async def run() -> None:
        settings = Settings()
        scope = uuid4().hex
        config = KisCoordinationConfig(
            minimum_interval_seconds=0.1,
            token_lock_seconds=2,
            wait_timeout_seconds=2,
            poll_interval_seconds=0.01,
        )
        first = ValkeyKisRequestCoordinator.from_url(
            settings.valkey_url.get_secret_value(), scope, config
        )
        second = ValkeyKisRequestCoordinator.from_url(
            settings.valkey_url.get_secret_value(), scope, config
        )
        reservations: list[float] = []

        async def reserve(coordinator: ValkeyKisRequestCoordinator) -> None:
            await coordinator.wait_for_request_slot()
            reservations.append(anyio.current_time())

        try:
            async with anyio.create_task_group() as task_group:
                _ = task_group.start_soon(reserve, first)
                _ = task_group.start_soon(reserve, second)
        finally:
            await first.close()
            await second.close()

        first_at, second_at = sorted(reservations)
        assert second_at - first_at >= 0.08

    anyio.run(run)


def test_valkey_coordinator_recovers_after_an_abandoned_lock_expires() -> None:
    async def run() -> None:
        settings = Settings()
        scope = uuid4().hex
        parsed_url = urlsplit(settings.valkey_url.get_secret_value())
        raw_client = Redis(
            host=parsed_url.hostname or "localhost",
            port=parsed_url.port or 6379,
            db=int(parsed_url.path.removeprefix("/") or "0"),
            decode_responses=True,
        )
        lock_key = f"auto-stock:kis:{scope}:token-lock"
        _ = await raw_client.set(lock_key, "abandoned-owner", px=50)
        await raw_client.aclose()
        coordinator = ValkeyKisRequestCoordinator.from_url(
            settings.valkey_url.get_secret_value(),
            scope,
            KisCoordinationConfig(
                minimum_interval_seconds=0.01,
                token_lock_seconds=1,
                wait_timeout_seconds=1,
                poll_interval_seconds=0.01,
            ),
        )
        issued = False

        async def issue_token() -> KisAccessToken:
            nonlocal issued
            issued = True
            return KisAccessToken(
                SecretStr("recovered-fixture-token"),
                datetime.now(UTC) + timedelta(seconds=65),
            )

        try:
            token = await coordinator.token(issue_token)
        finally:
            await coordinator.close()

        assert issued
        assert token.get_secret_value() == "recovered-fixture-token"

    anyio.run(run)


def test_valkey_failure_does_not_fall_back_to_token_issuance() -> None:
    async def run() -> None:
        config = KisCoordinationConfig(
            minimum_interval_seconds=0.01,
            token_lock_seconds=0.1,
            wait_timeout_seconds=0.1,
            poll_interval_seconds=0.01,
        )
        coordinator = ValkeyKisRequestCoordinator.from_url(
            "redis://127.0.0.1:1/0", uuid4().hex, config
        )
        issued = False

        async def issue_token() -> KisAccessToken:
            nonlocal issued
            issued = True
            return KisAccessToken(
                SecretStr("must-not-be-issued"),
                datetime.now(UTC) + timedelta(hours=1),
            )

        try:
            with pytest.raises(KisCoordinationError) as error:
                _ = await coordinator.token(issue_token)
        finally:
            await coordinator.close()

        assert not issued
        assert "127.0.0.1" not in str(error.value)
        assert "must-not-be-issued" not in str(error.value)

    anyio.run(run)
