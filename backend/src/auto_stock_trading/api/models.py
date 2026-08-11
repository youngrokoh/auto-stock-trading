from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from auto_stock_trading.application.health import ComponentState
from auto_stock_trading.settings.runtime import Environment


class ComponentHealthResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str
    status: ComponentState


class LivenessResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    environment: Environment
    service: Literal["api"] = "api"
    status: Literal["ok"] = "ok"
    version: str


class ReadinessResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    components: tuple[ComponentHealthResponse, ...]
    environment: Environment
    service: Literal["api"] = "api"
    status: Literal["ready", "degraded"]
    version: str
