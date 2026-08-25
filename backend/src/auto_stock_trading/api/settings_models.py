"""설정과 감사 화면의 응답 모델. 정책 상수를 그대로 옮긴다."""

from datetime import date
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class SettingsResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class CostRuleResponse(SettingsResponse):
    """날짜별 비용 규칙 한 세트. 비율은 문자열로 옮겨 표시에서 값이 흔들리지 않게 한다."""

    version: str
    effective_from: date
    fee_rate: str
    stock_slippage_rate: str
    etf_slippage_rate: str
    kospi_stock_sell_tax_rate: str
    kosdaq_stock_sell_tax_rate: str
    source: str
    # 오늘 적용되는 규칙인지. 화면이 날짜를 비교해 추론하지 않게 한다.
    current: bool


class CostRulesResponse(SettingsResponse):
    evaluated_on: date
    rules: tuple[CostRuleResponse, ...]
