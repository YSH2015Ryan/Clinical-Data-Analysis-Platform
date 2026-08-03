"""数据准备 schema（契约同源：docs/14 §3 PreparationDecisions/Preview/Job，2026-08-03）。"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PreparationDecisions(BaseModel):
    """docs/05 §8.2 五个决策点 + 引擎参数（医生做选择题）。"""

    outcome_terms: list[str] = Field(min_length=1, description="结局阳性诊断词条（任一命中=1）")
    outcome_scope: Literal["any", "index"] = "any"
    index_diagnosis: Literal["first", "last"] = "first"
    window_days: int = Field(default=30, ge=0, description="诊断前 N 天；0=不限")
    value_strategy: Literal["latest", "mean"] = "latest"
    value_column: str = "归一化值"
    exclude_susceptibility: bool = True
    clip_quantile: float = Field(default=0.99, ge=0, lt=1, description="0=不截断")
    top_n_items: int = Field(default=200, ge=1)


class PreparationPreviewRequest(BaseModel):
    diagnosis_dataset_id: uuid.UUID


class PreparationApplyRequest(BaseModel):
    diagnosis_dataset_id: uuid.UUID
    decisions: PreparationDecisions


class DiagnosisTerm(BaseModel):
    term: str
    count: int


class PreparationPreview(BaseModel):
    lab_columns: dict[str, str | None]
    diag_columns: dict[str, str | None]
    lab_rows: int
    diag_rows: int
    patients_intersection: int
    diagnosis_terms: list[DiagnosisTerm]
    susceptibility_rows: int
    suggested: dict[str, Any]


class PreparationJob(BaseModel):
    id: uuid.UUID
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    result_dataset_id: uuid.UUID | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
