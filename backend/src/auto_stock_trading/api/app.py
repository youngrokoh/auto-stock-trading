from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auto_stock_trading.adapters.health import PostgresHealthProbe, ValkeyHealthProbe
from auto_stock_trading.api.health import create_health_router
from auto_stock_trading.application.health import HealthProbe, HealthService
from auto_stock_trading.settings.runtime import Settings

ProbeFactory = Callable[[], HealthProbe]


def create_app(
    settings: Settings | None = None,
    database_probe_factory: ProbeFactory | None = None,
    cache_probe_factory: ProbeFactory | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    database_factory = database_probe_factory or (
        lambda: PostgresHealthProbe.from_url(runtime_settings.database_url.get_secret_value())
    )
    cache_factory = cache_probe_factory or (
        lambda: ValkeyHealthProbe.from_url(runtime_settings.valkey_url.get_secret_value())
    )
    health_service = HealthService(database=database_factory(), cache=cache_factory())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            await health_service.close()

    app = FastAPI(
        title="Auto Stock Trading API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.include_router(create_health_router(health_service, runtime_settings))
    return app


app = create_app()
