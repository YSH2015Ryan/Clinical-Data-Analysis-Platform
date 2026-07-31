"""分析运行 API schemas（docs/14 AnalysisRunCreate/AnalysisRun/AnalysisRunDetail/RunProgress）。"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskType = Literal["survival", "classification", "regression"]


class AnalysisRunCreate(BaseModel):
    dataset_version_id: uuid.UUID
    task_type: TaskType
    preprocess_config: dict[str, Any]
    selected_models: list[str] = Field(min_length=1)
    model_params: dict[str, dict[str, Any]] = {}


class AnalysisRunOut(BaseModel):
    id: uuid.UUID
    status: str
    task_type: str
    created_at: datetime


class AnalysisRunDetail(AnalysisRunOut):
    task_detection: dict[str, Any] | None
    error: str | None


class RunProgress(BaseModel):
    status: str
    percent: int = Field(ge=0, le=100)
    current_step: str | None = None
    models: dict[str, str]
    errors: dict[str, str] = {}  # 失败模型错误信息（14 章 2026-07-29 新增可选字段）
