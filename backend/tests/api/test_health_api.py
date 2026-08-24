from typing import final

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.settings.runtime import Environment, Settings
from tests.api.automation_stub import NoAutomationReset


@final
class StubProbe:
    _healthy: bool
    closed: bool

    def __init__(self, *, healthy: bool) -> None:
        self._healthy = healthy
        self.closed = False

    async def check(self) -> bool:
        return self._healthy

    async def close(self) -> None:
        self.closed = True


def test_liveness_does_not_depend_on_infrastructure() -> None:
    app = create_app(
        automation_reset_factory=NoAutomationReset,
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=lambda: StubProbe(healthy=False),
        cache_probe_factory=lambda: StubProbe(healthy=False),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "test",
        "service": "api",
        "status": "ok",
        "version": "0.1.0",
    }


def test_readiness_reports_each_dependency() -> None:
    app = create_app(
        automation_reset_factory=NoAutomationReset,
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=lambda: StubProbe(healthy=True),
        cache_probe_factory=lambda: StubProbe(healthy=True),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "components": [
            {"name": "PostgreSQL", "status": "ok"},
            {"name": "Valkey", "status": "ok"},
        ],
        "environment": "test",
        "service": "api",
        "status": "ready",
        "version": "0.1.0",
    }


def test_readiness_is_degraded_when_a_dependency_is_unavailable() -> None:
    app = create_app(
        automation_reset_factory=NoAutomationReset,
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=lambda: StubProbe(healthy=True),
        cache_probe_factory=lambda: StubProbe(healthy=False),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["components"] == [
        {"name": "PostgreSQL", "status": "ok"},
        {"name": "Valkey", "status": "unavailable"},
    ]


def test_browser_status_reports_degraded_without_an_http_error() -> None:
    app = create_app(
        automation_reset_factory=NoAutomationReset,
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=lambda: StubProbe(healthy=False),
        cache_probe_factory=lambda: StubProbe(healthy=False),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/status")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
