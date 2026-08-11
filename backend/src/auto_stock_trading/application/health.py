from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class HealthProbe(Protocol):
    async def check(self) -> bool: ...

    async def close(self) -> None: ...


class ComponentState(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    status: ComponentState


@dataclass(frozen=True, slots=True)
class Readiness:
    components: tuple[ComponentHealth, ...]

    @property
    def ready(self) -> bool:
        return all(component.status is ComponentState.OK for component in self.components)


@dataclass(frozen=True, slots=True)
class HealthService:
    database: HealthProbe
    cache: HealthProbe

    async def readiness(self) -> Readiness:
        database_is_healthy = await self.database.check()
        cache_is_healthy = await self.cache.check()
        return Readiness(
            components=(
                ComponentHealth(
                    name="PostgreSQL",
                    status=(
                        ComponentState.OK if database_is_healthy else ComponentState.UNAVAILABLE
                    ),
                ),
                ComponentHealth(
                    name="Valkey",
                    status=ComponentState.OK if cache_is_healthy else ComponentState.UNAVAILABLE,
                ),
            )
        )

    async def close(self) -> None:
        await self.database.close()
        await self.cache.close()
