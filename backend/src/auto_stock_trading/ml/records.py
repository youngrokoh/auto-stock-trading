"""모델 저장 레코드(ML 신호 계약 §저장)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ModelRecord:
    model_id: UUID
    name: str
    version: str
    algorithm: str
    feature_version: str
    target_definition: str
    train_start: date
    train_end: date
    embargo_days: int
    horizon_days: int
    # 엠바고가 끝나는 첫 거래일. 학습 시점 달력으로 계산해 저장한다(ADR-0012 결정 4).
    out_of_sample_start: date | None
    universe_size: int
    train_sample_count: int
    hyperparameters_json: str
    seed: int
    # 네이티브 포맷 텍스트. pickle은 쓰지 않는다.
    artifact: str
    input_bar_version_hash: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ModelEvaluationRecord:
    fold_index: int
    valid_start: date
    valid_end: date
    sample_count: int
    metric_name: str
    metric_value: float


@dataclass(frozen=True, slots=True)
class FeatureImportanceRecord:
    model_id: UUID
    feature_name: str
    importance: float
