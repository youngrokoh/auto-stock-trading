from typing import TYPE_CHECKING

from fastapi import APIRouter, Response, status

from auto_stock_trading.api.models import (
    ComponentHealthResponse,
    LivenessResponse,
    ReadinessResponse,
)

if TYPE_CHECKING:
    from auto_stock_trading.application.health import HealthService
    from auto_stock_trading.settings.runtime import Settings


def create_health_router(service: HealthService, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/health", tags=["health"])

    async def liveness() -> LivenessResponse:
        return LivenessResponse(environment=settings.environment, version="0.1.0")

    async def collect_readiness() -> ReadinessResponse:
        report = await service.readiness()
        readiness_status = "ready" if report.ready else "degraded"
        return ReadinessResponse(
            components=tuple(
                ComponentHealthResponse(name=component.name, status=component.status)
                for component in report.components
            ),
            environment=settings.environment,
            status=readiness_status,
            version="0.1.0",
        )

    async def readiness(response: Response) -> ReadinessResponse:
        report = await collect_readiness()
        if report.status == "degraded":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return report

    async def browser_status() -> ReadinessResponse:
        return await collect_readiness()

    router.add_api_route("/live", liveness, methods=["GET"], response_model=LivenessResponse)
    router.add_api_route(
        "/ready",
        readiness,
        methods=["GET"],
        response_model=ReadinessResponse,
    )
    router.add_api_route(
        "/status",
        browser_status,
        methods=["GET"],
        response_model=ReadinessResponse,
    )
    return router
