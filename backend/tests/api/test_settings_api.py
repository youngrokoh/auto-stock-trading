"""설정과 감사 화면이 읽는 정책 조회(거래 안전 정책 §5).

거래비용 규칙은 코드 상수다. 화면이 값을 만들지 않도록 상수를 그대로 노출하되, **날짜별 규칙 세트가
언제부터 유효한지와 근거 구분**을 함께 준다 — 과거 백테스트에 현재 규칙을 소급하지 않는다는 계약이
화면에서도 읽혀야 한다.
"""

from typing import final

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.api.settings_models import CostRulesResponse
from auto_stock_trading.settings.runtime import Environment, Settings
from tests.api.automation_stub import NoAutomationReset


@final
class StubProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _client() -> TestClient:
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        automation_reset_factory=NoAutomationReset,
    )
    return TestClient(app)


def test_cost_rules_are_returned_newest_first() -> None:
    response = _client().get("/api/settings/cost-rules")

    assert response.status_code == 200
    payload = CostRulesResponse.model_validate(response.json())
    assert payload.rules
    effective = [rule.effective_from for rule in payload.rules]
    assert effective == sorted(effective, reverse=True)


def test_every_rule_carries_its_basis() -> None:
    """연구 가정인지 정책 현행 표인지가 값과 함께 보여야 한다."""
    payload = CostRulesResponse.model_validate(_client().get("/api/settings/cost-rules").json())

    assert all(rule.source for rule in payload.rules)
    assert all(rule.version for rule in payload.rules)


def test_rates_are_decimal_strings() -> None:
    """비율을 float로 주면 표시에서 값이 흔들린다. 문자열로 그대로 옮긴다."""
    payload = CostRulesResponse.model_validate(_client().get("/api/settings/cost-rules").json())

    rule = payload.rules[0]
    assert isinstance(rule.fee_rate, str)
    assert isinstance(rule.kospi_stock_sell_tax_rate, str)


def test_the_current_rule_is_marked() -> None:
    """오늘 적용되는 규칙이 무엇인지 화면이 추론하지 않게 한다."""
    payload = CostRulesResponse.model_validate(_client().get("/api/settings/cost-rules").json())

    current = [rule for rule in payload.rules if rule.current]
    assert len(current) == 1
