"""分析运行 API schemas（docs/14 AnalysisRunCreate/AnalysisRun/AnalysisRunDetail/RunProgress）。"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskType = Literal["survival", "classification", "regression", "time_series"]


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


class ModelMetricsRow(BaseModel):
    """性能表行（docs/14 ModelMetricsRow）；FAILED 行 metrics 为 null 并标注 error。"""

    model_key: str
    status: str
    metrics: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None


class ChartAsset(BaseModel):
    """对比图表（docs/14 ChartAsset；T6.2 填充 data，报告 PNG 与前端 JSON 同源）。"""

    kind: str
    title: str
    data: dict[str, Any] = {}
    image_uri: str | None = None


class ComparisonResult(BaseModel):
    table: list[ModelMetricsRow]
    ranking: list[str]
    recommendation: dict[str, Any]
    charts: list[ChartAsset]


class IterateRequest(BaseModel):
    """T6.13 对话式迭代提问（docs/14 POST /analysis-runs/{id}/iterate）。"""

    question: str = Field(min_length=1, max_length=500)


class RerunSuggestion(BaseModel):
    """结构化重跑建议：列名/模型均已按数据集真实列与任务可用模型白名单校验。"""

    summary: str
    add_features: list[str] = []
    drop_features: list[str] = []
    selected_models: list[str] | None = None  # None = 模型集无需调整


class IterateResponse(BaseModel):
    answer: str
    suggestion: RerunSuggestion | None
    llm_enhanced: bool  # True=LLM 增强回答；False=规则回退
    dataset_id: uuid.UUID  # 「按建议重跑」跳转向导的数据集预选
    project_id: uuid.UUID  # 向导路由所需项目 id
