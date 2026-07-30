"""推荐默认预处理配置生成器（docs/06 §2「推荐默认配置」按钮、§3.1 长表适配）。

按列类型（T2.3 infer_dtype）与语义（T2.3 recognize_semantic）从数据自动生成
合法 DSL：长表（重复主键 + 名称/值列对）自动插入 reshape；id 列自动删除；
类别列缺失插补 mode；target 取 FollowUp/Event/Label 语义列；二值结局分层。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

from typing import Any

import pandas as pd

from app.engines.columns import infer_dtype, recognize_semantic

# 长表名称列基数上限（检验项目字典量级）
_LONG_NAME_MAX_UNIQUE = 50
# 长表主键最小基数（少于 3 个实体无从透视）
_LONG_ID_MIN_UNIQUE = 3


def _detect_long_format(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """检测长表（EAV）结构：重复主键 + 名称列 + 数值列（docs/06 §3.1）。

    判别：名称列 = 基数最小的候选键列；主键 = 基数最大的重复键列；
    且每个主键组平均覆盖 ≥2 个不同名称（宽表的「伪主键」每组只有 1 行，被此排除）。
    命中返回 (id_col, name_col, value_col)，否则 None。
    """
    value_col: str | None = None
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) and df[col].nunique() > 2:
            value_col = col
            break
    if value_col is None:
        return None
    key_candidates = [
        col
        for col in df.columns
        if col != value_col
        and not pd.api.types.is_float_dtype(df[col])
        and df[col].duplicated().any()
        and int(df[col].nunique()) >= 2
    ]
    if len(key_candidates) < 2:
        return None
    by_cardinality = sorted(key_candidates, key=lambda c: int(df[c].nunique()))
    name_col = by_cardinality[0]
    id_col = by_cardinality[-1]
    if int(df[name_col].nunique()) > _LONG_NAME_MAX_UNIQUE:
        return None
    if int(df[id_col].nunique()) < _LONG_ID_MIN_UNIQUE:
        return None
    if int(df[id_col].nunique()) <= int(df[name_col].nunique()):
        return None
    names_per_id = df.groupby(id_col)[name_col].nunique().mean()
    if float(names_per_id) < 2.0:
        return None
    return id_col, name_col, value_col


def recommend_config(df: pd.DataFrame, *, seed: int = 42) -> dict[str, Any]:
    """生成推荐 DSL（dict，可直接 validate_dsl / run_preprocess）。"""
    steps: list[dict[str, Any]] = []

    long_format = _detect_long_format(df)
    dropped_ids: list[str] = []
    if long_format is not None:
        id_col, name_col, value_col = long_format
        steps.append(
            {
                "type": "reshape",
                "params": {
                    "mode": "long_to_wide",
                    "index": id_col,
                    "columns": name_col,
                    "values": value_col,
                    "agg": "first",
                },
            }
        )
        dropped_ids.append(id_col)
    else:
        # 宽表：唯一 id 列不进模型
        dropped_ids = [c for c in df.columns if infer_dtype(df[c]) == "id"]

    if dropped_ids:
        steps.append({"type": "drop_columns", "params": {"columns": dropped_ids}})

    per_column = {
        c: "mode"
        for c in df.columns
        if c not in dropped_ids and infer_dtype(df[c]) in ("categorical", "datetime")
    }
    steps.append(
        {
            "type": "missing",
            "params": {"default": "median", "per_column": per_column, "drop_threshold": 0.5},
        }
    )
    steps.append(
        {"type": "outlier", "params": {"method": "iqr", "action": "clip", "columns": "continuous"}}
    )
    steps.append({"type": "encode", "params": {"method": "auto", "onehot_max_cardinality": 10}})
    steps.append({"type": "scale", "params": {"method": "standard", "columns": "continuous"}})
    steps.append(
        {"type": "feature_select", "params": {"method": "variance_threshold", "threshold": 0.0}}
    )

    target: dict[str, Any] = {}
    event_col: str | None = None
    for col in df.columns:
        hit = recognize_semantic(col, df[col])
        if hit.confidence < 0.85:
            continue
        if hit.semantic == "FollowUp" and "time_col" not in target:
            target["time_col"] = col
        elif hit.semantic == "Event" and "event_col" not in target:
            target["event_col"] = col
            event_col = col
        elif hit.semantic == "Label" and "label_col" not in target:
            target["label_col"] = col
    if "label_col" not in target and "event_col" in target and "time_col" not in target:
        # 仅二值结局（无随访时间）→ 分类任务标签
        target["label_col"] = target.pop("event_col")

    stratify_col = event_col or target.get("label_col")
    stratified = (
        stratify_col is not None and stratify_col in df.columns and df[stratify_col].nunique() <= 10
    )
    validation: dict[str, Any] = {
        "strategy": "stratified_kfold" if stratified else "kfold",
        "n_splits": 5,
        "seed": seed,
    }
    return {"target": target, "steps": steps, "validation": validation}
