"""Quick Fix 引擎（docs/05 §5）：4 种在线修复动作，纯 DataFrame 变换。

动作幂等可链式执行；每个动作产生一条 transform_log（随 DatasetVersion 落库，
可重放）；remap_semantic 不改数据，仅记录语义覆盖（供任务识别/预处理消费）。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.engines.columns import SEMANTIC_DICT

ACTION_TYPES = ("drop_column", "drop_duplicates", "to_missing", "remap_semantic")


@dataclass(frozen=True)
class QuickFixAction:
    type: str  # ACTION_TYPES 之一
    column: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


def apply_actions(
    df: pd.DataFrame, actions: list[QuickFixAction]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """顺序执行动作，返回（新 df, transform_log）。原 df 不被修改。"""
    out = df.copy()
    log: list[dict[str, Any]] = []
    for action in actions:
        out, entry = _apply_one(out, action)
        log.append(entry)
    return out, log


def _apply_one(df: pd.DataFrame, action: QuickFixAction) -> tuple[pd.DataFrame, dict[str, Any]]:
    base: dict[str, Any] = {"action": action.type, "column": action.column, "params": action.params}
    if action.type == "drop_column":
        _require_column(df, action.column)
        return df.drop(columns=[action.column]), {**base, "affected_rows": 0}
    if action.type == "drop_duplicates":
        before = len(df)
        out = df.drop_duplicates().reset_index(drop=True)
        return out, {**base, "affected_rows": before - len(out)}
    if action.type == "to_missing":
        col = _require_column(df, action.column)
        values = action.params.get("values")
        if values:
            mask = df[col].isin(values)
            out = df.copy()
            out.loc[mask, col] = None
            return out, {**base, "affected_rows": int(mask.sum())}
        # 默认：数值意图列的非数值 → 缺失（RV301 场景）
        coerced = pd.to_numeric(df[col], errors="coerce")
        mask = coerced.isna() & df[col].notna()
        out = df.copy()
        out[col] = coerced
        return out, {**base, "affected_rows": int(mask.sum())}
    if action.type == "remap_semantic":
        _require_column(df, action.column)
        semantic = action.params.get("semantic")
        if semantic not in SEMANTIC_DICT:
            allowed = "/".join(SEMANTIC_DICT)
            raise ValueError(f"语义 {semantic!r} 无效，可选：{allowed}")
        return df, {**base, "affected_rows": 0}
    raise ValueError(f"未知修复动作：{action.type}")


def _require_column(df: pd.DataFrame, column: str | None) -> str:
    if column is None or column not in df.columns:
        raise ValueError(f"列 {column!r} 不存在")
    return column
