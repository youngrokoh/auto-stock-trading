from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import pytest
from pydantic import SecretStr
from redis.asyncio import Redis

from auto_stock_trading.adapters.brokers.kis_coordination import (
    InMemoryKisRequestCoordinator,
    KisCoordinationConfig,
    KisCoordinationError,
)
from auto_stock_trading.adapters.brokers.kis_coordination_valkey import (
    ValkeyKisRequestCoordinator,
)
from auto_stock_trading.settings.runtime import Settings

_FAST = KisCoordinationConfig(
    minimum_interval_seconds=0.01,
    token_lock_seconds=2,
    wait_timeout_seconds=2,
    poll_interval_seconds=0.01,
)


def _raw_client(url: str) -> Redis:
    parsed_url = urlsplit(url)
    return Redis(
        host=parsed_url.hostname or "localhost",
        port=parsed_url.port or 6379,
        db=int(parsed_url.path.removeprefix("/") or "0"),
        decode_responses=True,
    )


def test_in_memory_coordinator_issues_the_approval_key_once() -> None:
    async def run() -> None:
        coordinator = InMemoryKisRequestCoordinator(_FAST)
        issued = 0

        async def issue() -> SecretStr:
            nonlocal issued
            issued += 1
            return SecretStr("fixture-approval-key")

        first = await coordinator.approval_key(issue)
        second = await coordinator.approval_key(issue)
        await coordinator.close()

        assert issued == 1
        assert first.get_secret_value() == "fixture-approval-key"
        assert second.get_secret_value() == "fixture-approval-key"

    anyio.run(run)


def test_in_memory_invalidation_forces_a_new_approval_key() -> None:
    async def run() -> None:
        coordinator = InMemoryKisRequestCoordinator(_FAST)
        issued = 0

        async def issue() -> SecretStr:
            nonlocal issued
            issued += 1
            return SecretStr(f"fixture-approval-key-{issued}")

        first = await coordinator.approval_key(issue)
        await coordinator.invalidate_approval_key()
        second = await coordinator.approval_key(issue)
        await coordinator.close()

        assert issued == 2
        assert first.get_secret_value() == "fixture-approval-key-1"
        assert second.get_secret_value() == "fixture-approval-key-2"

    anyio.run(run)


def test_valkey_coordinators_share_one_approval_key() -> None:
    async def run() -> None:
        settings = Settings()
        scope = uuid4().hex
        url = settings.valkey_url.get_secret_value()
        first = ValkeyKisRequestCoordinator.from_url(url, scope, _FAST)
        second = ValkeyKisRequestCoordinator.from_url(url, scope, _FAST)
        issued = 0
        keys: list[str] = []

        async def issue() -> SecretStr:
            nonlocal issued
            issued += 1
            await anyio.sleep(0.05)
            return SecretStr("shared-approval-key")

        async def collect(coordinator: ValkeyKisRequestCoordinator) -> None:
            key = await coordinator.approval_key(issue)
            keys.append(key.get_secret_value())

        try:
            async with anyio.create_task_group() as task_group:
                _ = task_group.start_soon(collect, first)
                _ = task_group.start_soon(collect, second)
        finally:
            await first.close()
            await second.close()

        assert issued == 1
        assert keys == ["shared-approval-key", "shared-approval-key"]

    anyio.run(run)


def test_shared_approval_key_expires_within_the_configured_window() -> None:
    async def run() -> None:
        settings = Settings()
        scope = uuid4().hex
        url = settings.valkey_url.get_secret_value()
        coordinator = ValkeyKisRequestCoordinator.from_url(url, scope, _FAST)

        async def issue() -> SecretStr:
            return SecretStr("expiring-approval-key")

        try:
            _ = await coordinator.approval_key(issue)
        finally:
            await coordinator.close()

        client = _raw_client(url)
        try:
            ttl = await client.ttl(f"auto-stock:kis:{scope}:approval")
        finally:
            await client.aclose()

        assert 0 < ttl <= _FAST.approval_ttl_seconds

    anyio.run(run)


def test_invalidating_the_shared_approval_key_forces_reissue() -> None:
    async def run() -> None:
        settings = Settings()
        scope = uuid4().hex
        url = settings.valkey_url.get_secret_value()
        first = ValkeyKisRequestCoordinator.from_url(url, scope, _FAST)
        second = ValkeyKisRequestCoordinator.from_url(url, scope, _FAST)
        issued = 0

        async def issue() -> SecretStr:
            nonlocal issued
            issued += 1
            return SecretStr(f"approval-key-{issued}")

        try:
            _ = await first.approval_key(issue)
            await first.invalidate_approval_key()
            reissued = await second.approval_key(issue)
        finally:
            await first.close()
            await second.close()

        assert issued == 2
        assert reissued.get_secret_value() == "approval-key-2"

    anyio.run(run)


def test_valkey_failure_does_not_fall_back_to_approval_key_issuance() -> None:
    async def run() -> None:
        coordinator = ValkeyKisRequestCoordinator.from_url(
            "redis://127.0.0.1:1/0",
            uuid4().hex,
            KisCoordinationConfig(
                minimum_interval_seconds=0.01,
                token_lock_seconds=0.1,
                wait_timeout_seconds=0.1,
                poll_interval_seconds=0.01,
            ),
        )
        issued = False

        async def issue() -> SecretStr:
            nonlocal issued
            issued = True
            return SecretStr("must-not-be-issued")

        try:
            with pytest.raises(KisCoordinationError) as error:
                _ = await coordinator.approval_key(issue)
        finally:
            await coordinator.close()

        assert not issued
        assert "must-not-be-issued" not in str(error.value)

    anyio.run(run)
