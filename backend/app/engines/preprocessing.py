"""预处理 DSL schema（docs/06 §2、docs/14 §3 PreprocessConfig 强类型落地）。

配置即数据：AnalysisRunCreate.preprocess_config 与本 schema 同源；非法 DSL
在 API 层映射 400 VALIDATION_ERROR（docs/14 PreprocessStep.params 约定）。
derive 表达式在此仅做形状校验，运行时由 simpleeval 白名单求值（T3.3）。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------- target / validation ----------


class TargetSpec(BaseModel):
    """结局定义：survival 用 time_col+event_col，分类/回归用 label_col（docs/14）。"""

    model_config = ConfigDict(extra="forbid")

    time_col: str | None = None
    event_col: str | None = None
    label_col: str | None = None


class ValidationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal[
        "stratified_kfold",
        "kfold",
        "group_kfold",
        "stratified_group_kfold",
        "time_series_split",
    ]
    n_splits: int = Field(default=5, ge=2, le=10)
    test_size: float = Field(default=0.2, gt=0.0, lt=0.9)
    seed: int = 42
    group_col: str | None = None
    time_col: str | None = None
    prediction_time_col: str | None = None


# ---------- steps（discriminated union，type 枚举与 docs/14 一致） ----------


class ReshapeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["long_to_wide"]
    index: str = Field(min_length=1)
    columns: str = Field(min_length=1)
    values: str = Field(min_length=1)
    agg: Literal["first", "mean", "sum", "max", "min", "count"] = "first"


class ReshapeStep(BaseModel):
    type: Literal["reshape"]
    params: ReshapeParams


class DropColumnsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=1)


class DropColumnsStep(BaseModel):
    type: Literal["drop_columns"]
    params: DropColumnsParams


_MISSING_STRATEGIES = ("median", "mean", "mode", "knn", "constant")


class MissingParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: Literal["median", "mean", "mode", "knn", "constant"] = "median"
    per_column: dict[str, str] = {}
    drop_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    constant_value: Any = 0

    @field_validator("per_column")
    @classmethod
    def _per_column_strategies(cls, v: dict[str, str]) -> dict[str, str]:
        bad = {c: s for c, s in v.items() if s not in _MISSING_STRATEGIES}
        if bad:
            raise ValueError(
                f"per_column 存在非法策略 {bad}，可选：{'/'.join(_MISSING_STRATEGIES)}"
            )
        return v


class MissingStep(BaseModel):
    type: Literal["missing"]
    params: MissingParams


ColumnSelector = Literal["continuous"] | list[str]


class OutlierParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["iqr", "zscore", "isolation_forest"] = "iqr"
    action: Literal["clip", "drop"] = "clip"
    columns: ColumnSelector = "continuous"
    zscore_threshold: float = Field(default=3.0, gt=0.0)


class OutlierStep(BaseModel):
    type: Literal["outlier"]
    params: OutlierParams


class EncodeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["auto", "onehot", "ordinal", "target"] = "auto"
    onehot_max_cardinality: int = Field(default=10, ge=2, le=100)
    ordinal_columns: dict[str, list[str]] = {}


class EncodeStep(BaseModel):
    type: Literal["encode"]
    params: EncodeParams


class ScaleParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["standard", "minmax", "robust"] = "standard"
    columns: ColumnSelector = "continuous"


class ScaleStep(BaseModel):
    type: Literal["scale"]
    params: ScaleParams


class FeatureSelectParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["variance_threshold", "correlation", "univariate", "lasso"] = (
        "variance_threshold"
    )
    threshold: float = Field(default=0.0, ge=0.0)


class FeatureSelectStep(BaseModel):
    type: Literal["feature_select"]
    params: FeatureSelectParams


_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DeriveExpr(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    expr: str = Field(min_length=1, max_length=500)

    @field_validator("name")
    @classmethod
    def _valid_identifier(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"派生列名 {v!r} 非法：须为标识符（字母/数字/下划线，字母开头）")
        return v


class DeriveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expressions: list[DeriveExpr] = Field(min_length=1)


class DeriveStep(BaseModel):
    type: Literal["derive"]
    params: DeriveParams


Step = Annotated[
    ReshapeStep
    | DropColumnsStep
    | MissingStep
    | OutlierStep
    | EncodeStep
    | ScaleStep
    | FeatureSelectStep
    | DeriveStep,
    Field(discriminator="type"),
]


# ---------- 顶层 ----------


class PreprocessConfig(BaseModel):
    """与 docs/14 PreprocessConfig 一一对应：target/steps/validation 必填，steps ≥1。"""

    model_config = ConfigDict(extra="forbid")

    target: TargetSpec
    steps: list[Step] = Field(min_length=1)
    validation: ValidationSpec


def validate_dsl(raw: dict[str, Any]) -> PreprocessConfig:
    """解析并校验 DSL；非法时抛 pydantic.ValidationError（API 层映射 400）。"""
    return PreprocessConfig.model_validate(raw)
