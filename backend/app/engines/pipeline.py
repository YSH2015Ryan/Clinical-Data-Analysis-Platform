"""预处理流水线组装 / CV 折迭代 / Snapshot 构建（docs/06 §4，docs/18 T3.4）。

- build_pipeline：PreprocessConfig → sklearn.Pipeline（步骤名 ``{i}_{type}``）；
- iter_cv_splits：按 validation 策略产出 (train_idx, val_idx)，防泄漏的边界：
  调用方必须只在 train_idx 上 fit、再 transform val_idx（docs/06 §4 流程图）；
- run_preprocess：全量顺序执行，产出特征矩阵 + Snapshot（步骤顺序/参数/
  拟合统计量/输入 hash/库版本/seed）+ 每步摘要（行列数变化、警告）。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from typing import Any, cast

import numpy as np
import pandas as pd
import sklearn
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import Pipeline

from app.engines.preprocess_steps import (
    DeriveTransformer,
    DropColumnsTransformer,
    EncodeTransformer,
    FeatureSelectTransformer,
    MissingTransformer,
    OutlierTransformer,
    ReshapeTransformer,
    ScaleTransformer,
)
from app.engines.preprocessing import (
    DeriveStep,
    DropColumnsStep,
    EncodeStep,
    FeatureSelectStep,
    MissingStep,
    OutlierStep,
    PreprocessConfig,
    ReshapeStep,
    ScaleStep,
    Step,
    ValidationSpec,
)


def make_transformer(step: Step) -> Any:
    """DSL 步骤 → 转换器实例（参数与 docs/14 PreprocessStep 同源）。"""
    if isinstance(step, ReshapeStep):
        p = step.params
        return ReshapeTransformer(
            mode=p.mode, index=p.index, columns=p.columns, values=p.values, agg=p.agg
        )
    if isinstance(step, DropColumnsStep):
        return DropColumnsTransformer(columns=list(step.params.columns))
    if isinstance(step, MissingStep):
        mp = step.params
        return MissingTransformer(
            default=mp.default,
            per_column=dict(mp.per_column),
            drop_threshold=mp.drop_threshold,
            constant_value=mp.constant_value,
        )
    if isinstance(step, OutlierStep):
        op = step.params
        return OutlierTransformer(
            method=op.method,
            action=op.action,
            columns=op.columns,
            zscore_threshold=op.zscore_threshold,
        )
    if isinstance(step, EncodeStep):
        ep = step.params
        return EncodeTransformer(
            method=ep.method,
            onehot_max_cardinality=ep.onehot_max_cardinality,
            ordinal_columns=dict(ep.ordinal_columns),
        )
    if isinstance(step, ScaleStep):
        return ScaleTransformer(method=step.params.method, columns=step.params.columns)
    if isinstance(step, FeatureSelectStep):
        return FeatureSelectTransformer(method=step.params.method, threshold=step.params.threshold)
    if isinstance(step, DeriveStep):
        return DeriveTransformer(
            expressions=[{"name": e.name, "expr": e.expr} for e in step.params.expressions]
        )
    raise ValueError(f"未知步骤类型：{step!r}")  # pragma: no cover（判别联合已穷尽）


def build_pipeline(cfg: PreprocessConfig) -> Pipeline:
    """PreprocessConfig → sklearn.Pipeline，步骤名 ``{i}_{type}``（Snapshot 取回统计量用）。"""
    return Pipeline(
        [(f"{i}_{step.type}", make_transformer(step)) for i, step in enumerate(cfg.steps)]
    )


SplitIterator = Iterator[tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]]


def iter_cv_splits(df: pd.DataFrame, spec: ValidationSpec, y: pd.Series | None) -> SplitIterator:
    """按 validation 策略产出 (train_idx, val_idx) 位置索引；seed 固定可复现。"""
    if spec.strategy == "stratified_kfold":
        if y is None:
            raise ValueError("stratified_kfold 需要 y 以维持类别比例")
        splitter = StratifiedKFold(n_splits=spec.n_splits, shuffle=True, random_state=spec.seed)
        return cast(SplitIterator, splitter.split(df, y))
    splitter = KFold(n_splits=spec.n_splits, shuffle=True, random_state=spec.seed)
    return cast(SplitIterator, splitter.split(df))


def library_versions() -> dict[str, str]:
    """Snapshot 的库版本段（docs/06 §4：可复现性信息）。"""
    return {
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "sklearn": sklearn.__version__,
        "simpleeval": importlib_metadata.version("simpleeval"),
    }


def _jsonable(value: Any) -> Any:
    """把 statistics_ 中的 numpy/pandas 标量递归转为 JSON 可序列化类型。"""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if isinstance(value, float) and np.isnan(value):
        return None
    # 处理 Pandas 时间类型（Timestamp, Timedelta 等）
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.total_seconds()
    return value


@dataclass
class PreprocessResult:
    """run_preprocess 产物：特征矩阵 + Snapshot（写 preprocess_snapshots.steps）+ 逐步摘要。"""

    features: pd.DataFrame
    snapshot: dict[str, Any]
    summary: list[dict[str, Any]] = field(default_factory=list)


def run_preprocess(
    df: pd.DataFrame,
    cfg: PreprocessConfig,
    *,
    y: pd.Series | None = None,
    input_hash: str = "",
) -> PreprocessResult:
    """全量顺序执行预处理（最终 fit，docs/06 §4 右侧支线）。

    CV 场景请用 build_pipeline + iter_cv_splits 在每折内 fit/transform；
    本函数产出 Snapshot（步骤顺序/参数/拟合统计量/输入 hash/库版本/seed）
    与逐步摘要（报告「预处理过程」章节数据源，docs/06 §5）。
    """
    out = df.copy()
    steps_snapshot: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []

    for i, step in enumerate(cfg.steps):
        transformer = make_transformer(step)
        rows_in, cols_in = out.shape
        transformer.fit(out, y)
        out = transformer.transform(out)
        statistics = getattr(transformer, "statistics_", {})
        steps_snapshot.append(
            {
                "order": i,
                "type": step.type,
                "params": step.params.model_dump(mode="json"),
                "statistics": _jsonable(statistics),
            }
        )
        summary.append(
            {
                "step": step.type,
                "rows_in": int(rows_in),
                "rows_out": int(out.shape[0]),
                "cols_in": int(cols_in),
                "cols_out": int(out.shape[1]),
                "warnings": _jsonable(statistics.get("warnings", {})),
            }
        )

    snapshot: dict[str, Any] = {
        "steps": steps_snapshot,
        "input_hash": input_hash,
        "library_versions": library_versions(),
        "seed": cfg.validation.seed,
        "validation": cfg.validation.model_dump(mode="json"),
    }
    return PreprocessResult(features=out, snapshot=snapshot, summary=summary)
