"""실전 전환 게이트 조회 API. 판정 결과를 그대로 노출한다.

게이트는 **막는 것이 내용**이다. 통과 여부만 주면 무엇이 왜 막는지가 사라지므로, 조건별 상태와
판정 불가 사유를 함께 준다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Protocol

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from auto_stock_trading.domain.gate.readiness import evaluate_gate, initial_live_limits
from auto_stock_trading.domain.risk.limits import seoul_trading_date

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from auto_stock_trading.domain.gate.readiness import GateMeasurements

type Clock = Callable[[], datetime]


class GateReader(Protocol):
    async def measurements(self, environment: str, as_of: date) -> GateMeasurements: ...

    async def close(self) -> None: ...


class GateResponseModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class GateConditionResponse(GateResponseModel):
    code: str
    section: str
    requirement: str
    threshold: str | None
    measured: str | None
    state: str
    reason_code: str | None


class GateLimitResponse(GateResponseModel):
    code: str
    item: str
    value: str


class GateReadinessResponse(GateResponseModel):
    environment: str
    live_enabled: bool
    passed: bool
    evaluated_at: datetime
    blocking_codes: tuple[str, ...]
    conditions: tuple[GateConditionResponse, ...]
    initial_limits: tuple[GateLimitResponse, ...]


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_gate_router(
    reader: GateReader,
    environment: str,
    *,
    live_enabled: bool,
    clock: Clock = utc_now,
) -> APIRouter:
    router = APIRouter(prefix="/api/gate", tags=["gate"])

    async def readiness() -> GateReadinessResponse:
        now = clock()
        measurements = await reader.measurements(environment, seoul_trading_date(now))
        result = evaluate_gate(measurements, now)
        return GateReadinessResponse(
            environment=environment,
            live_enabled=live_enabled,
            passed=result.passed,
            evaluated_at=result.evaluated_at,
            blocking_codes=result.blocking_codes,
            conditions=tuple(
                GateConditionResponse(
                    code=condition.code,
                    section=condition.section.value,
                    requirement=condition.requirement,
                    threshold=condition.threshold,
                    measured=condition.measured,
                    state=condition.state.value,
                    reason_code=condition.reason_code,
                )
                for condition in result.conditions
            ),
            initial_limits=tuple(
                GateLimitResponse(code=limit.code, item=limit.item, value=limit.value)
                for limit in initial_live_limits()
            ),
        )

    router.add_api_route(
        "/readiness",
        readiness,
        methods=["GET"],
        description=(
            "실전 전환 게이트의 조건별 상태를 반환한다. 저장된 사실로 판정할 수 없는 조건은 "
            "`not_measurable`과 사유 코드로 남기며 통과로 보이지 않는다."
        ),
    )
    return router
