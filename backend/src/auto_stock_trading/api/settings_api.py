"""설정과 감사 조회 API. 값을 바꾸는 경로는 만들지 않는다.

거래 안전 정책의 한도와 비용 규칙은 **코드 상수이며 정책 문서 개정과 사람 승인 없이 바뀌지 않는다.**
화면에서 고칠 수 있게 만들면 그 경계가 무너지므로 조회만 제공한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from auto_stock_trading.api.settings_models import CostRuleResponse, CostRulesResponse
from auto_stock_trading.domain.strategies.costs import COST_RULE_SETS, cost_rule_set_for

if TYPE_CHECKING:
    from collections.abc import Callable

_SEOUL = ZoneInfo("Asia/Seoul")

type Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_settings_router(clock: Clock = utc_now) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["settings"])

    async def cost_rules() -> CostRulesResponse:
        today = clock().astimezone(_SEOUL).date()
        current = cost_rule_set_for(today)
        rules = sorted(COST_RULE_SETS, key=lambda rule: rule.effective_from, reverse=True)
        return CostRulesResponse(
            evaluated_on=today,
            rules=tuple(
                CostRuleResponse(
                    version=rule.version,
                    effective_from=rule.effective_from,
                    fee_rate=str(rule.fee_rate),
                    stock_slippage_rate=str(rule.stock_slippage_rate),
                    etf_slippage_rate=str(rule.etf_slippage_rate),
                    kospi_stock_sell_tax_rate=str(rule.kospi_stock_sell_tax_rate),
                    kosdaq_stock_sell_tax_rate=str(rule.kosdaq_stock_sell_tax_rate),
                    source=rule.source,
                    current=rule.version == current.version,
                )
                for rule in rules
            ),
        )

    router.add_api_route(
        "/cost-rules",
        cost_rules,
        methods=["GET"],
        description=(
            "거래 안전 정책 §5의 날짜별 비용 규칙을 최신순으로 반환한다. 오늘 적용되는 규칙을 "
            "표시하며 값을 바꾸는 경로는 제공하지 않는다."
        ),
    )
    return router
