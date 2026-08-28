"""Quick Fix 引擎（docs/05 §5）：在线修复动作，纯 DataFrame 变换。

动作幂等可链式执行；每个动作产生一条 transform_log（随 DatasetVersion 落库，
可重放）；remap_semantic 不改数据，仅记录语义覆盖（供任务识别/预处理消费）。

T6.8：动作从 4 种扩展到 10 种（rename_column / pivot_long_to_wide /
winsorize_outliers / impute_missing / drop_rows_with_pattern / normalize_units），
覆盖高发校验规则（RV201/RV501/RV601/RV802/RV804 等）的一键修复。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.engines.columns import SEMANTIC_DICT

ACTION_TYPES = (
    "drop_column",
    "drop_duplicates",
    "to_missing",
    "remap_semantic",
    # T6.8 扩展
    "rename_column",
    "pivot_long_to_wide",
    "winsorize_outliers",
    "impute_missing",
    "drop_rows_with_pattern",
    "normalize_units",
)


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
    # ---------- T6.8 扩展动作 ----------
    if action.type == "rename_column":
        col = _require_column(df, action.column)
        return _rename_column(df, col, action.params, base)
    if action.type == "pivot_long_to_wide":
        return _pivot_long_to_wide(df, action.params, base)
    if action.type == "winsorize_outliers":
        col = _require_column(df, action.column)
        return _winsorize_outliers(df, col, action.params, base)
    if action.type == "impute_missing":
        col = _require_column(df, action.column)
        return _impute_missing(df, col, action.params, base)
    if action.type == "drop_rows_with_pattern":
        col = _require_column(df, action.column)
        return _drop_rows_with_pattern(df, col, action.params, base)
    if action.type == "normalize_units":
        col = _require_column(df, action.column)
        return _normalize_units(df, col, action.params, base)
    raise ValueError(f"未知修复动作：{action.type}")


def _rename_column(
    df: pd.DataFrame, column: str, params: dict[str, Any], base: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """重命名列（RV003 重复列名场景）。"""
    new_name = params.get("new_name")
    if not new_name:
        raise ValueError("缺少必需参数 new_name")
    if new_name in df.columns:
        raise ValueError(f"列名 {new_name!r} 已存在，请换一个名字")
    out = df.rename(columns={column: new_name})
    return out, {**base, "affected_rows": 0, "new_name": new_name}


def _pivot_long_to_wide(
    df: pd.DataFrame, params: dict[str, Any], base: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """长表转宽表（RV801）：一行一条检验记录 → 一行一个患者。

    同一患者同一项目多条记录取均值（如重复测量的血钾）。
    透视为数值失败的项目列保持原样（pandas 自行处理）。
    """
    id_column = params.get("id_column")
    item_column = params.get("item_column")
    value_column = params.get("value_column")
    if not (id_column and item_column and value_column):
        raise ValueError("缺少必需参数 id_column, item_column, value_column")
    for c in (id_column, item_column, value_column):
        _require_column(df, c)
    values = pd.to_numeric(df[value_column], errors="coerce")
    work = df.assign(**{value_column: values})
    wide = work.pivot_table(
        index=id_column, columns=item_column, values=value_column, aggfunc="mean"
    )
    # 非透视列（如年龄/性别）按每个 id 取首条记录保留
    others = [c for c in df.columns if c not in {id_column, item_column, value_column}]
    if others:
        extra = df.groupby(id_column)[others].first()
        wide = extra.join(wide)
    out = wide.reset_index()
    out.columns = [str(c) for c in out.columns]
    return out, {**base, "affected_rows": len(df), "result_rows": len(out)}


def _winsorize_outliers(
    df: pd.DataFrame, column: str, params: dict[str, Any], base: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """异常值截尾（RV501/RV804）。

    显式传 lower/upper_percentile → 按分位数截尾；
    缺省 → IQR×1.5 界截尾（温和，不扰动无异常数据）。
    """
    s = pd.to_numeric(df[column], errors="coerce")
    if s.notna().sum() == 0:
        raise ValueError(f"列 {column!r} 不是数值类型，无法截尾")
    lower_p = params.get("lower_percentile")
    upper_p = params.get("upper_percentile")
    clean = s.dropna()
    if lower_p is not None or upper_p is not None:
        # 下界取 higher、上界取 lower 插值:截尾点本身是「合理值」,避免把边界值挤出
        lo = clean.quantile(float(lower_p if lower_p is not None else 0.0), interpolation="higher")
        hi = clean.quantile(float(upper_p if upper_p is not None else 1.0), interpolation="lower")
    else:
        q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    clipped = s.clip(lower=lo, upper=hi)
    affected = int((clipped != s).sum())
    out = df.copy()
    out[column] = clipped
    return out, {**base, "affected_rows": affected, "lower": float(lo), "upper": float(hi)}


def _impute_missing(
    df: pd.DataFrame, column: str, params: dict[str, Any], base: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """缺失值插补（RV201）：median / mean / mode / constant / auto(数值→median,否则 mode)。"""
    s = df[column]
    strategy = params.get("strategy", "auto")
    if strategy == "auto":
        strategy = "median" if pd.api.types.is_numeric_dtype(s) else "mode"
    if strategy == "median":
        fill = float(pd.to_numeric(s, errors="coerce").median())
    elif strategy == "mean":
        fill = float(pd.to_numeric(s, errors="coerce").mean())
    elif strategy == "mode":
        m = s.mode(dropna=True)
        if m.empty:
            raise ValueError(f"列 {column!r} 全部为缺失，无法众数插补")
        fill = m.iloc[0]
    elif strategy == "constant":
        if "fill_value" not in params:
            raise ValueError("strategy=constant 缺少必需参数 fill_value")
        fill = params["fill_value"]
    else:
        raise ValueError(f"未知插补策略：{strategy!r}（可选 median/mean/mode/constant/auto）")
    mask = s.isna()
    out = df.copy()
    out[column] = s.fillna(fill)
    fill_log = float(fill) if isinstance(fill, (float, int)) and not isinstance(fill, bool) else fill
    return out, {
        **base,
        "affected_rows": int(mask.sum()),
        "strategy": strategy,
        "fill_value": fill_log,
    }


def _drop_rows_with_pattern(
    df: pd.DataFrame, column: str, params: dict[str, Any], base: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """删除列值匹配正则的行（RV802 药敏记录场景）。"""
    pattern = params.get("pattern")
    if not pattern:
        raise ValueError("缺少必需参数 pattern")
    case = bool(params.get("case_sensitive", False))
    mask = df[column].astype(str).str.contains(pattern, case=case, regex=True) & df[column].notna()
    out = df.loc[~mask].reset_index(drop=True)
    return out, {**base, "affected_rows": int(mask.sum())}


def _normalize_units(
    df: pd.DataFrame, column: str, params: dict[str, Any], base: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """单位标准化（RV803）：按 conversions {单位: {factor, target}} 换算并统一单位列。

    例:{"mg/dL": {"factor": 0.0555, "target": "mmol/L"}} → 100 mg/dL 血糖 ≈ 5.55 mmol/L。
    """
    unit_column = params.get("unit_column")
    if not unit_column:
        raise ValueError("缺少必需参数 unit_column")
    _require_column(df, unit_column)
    conversions: dict[str, dict[str, Any]] = params.get("conversions") or {}
    if not conversions:
        raise ValueError("缺少必需参数 conversions（如 {'mg/dL': {'factor': 0.0555, 'target': 'mmol/L'}}）")
    out = df.copy()
    # 统一转为 float,避免 int 列赋换算后小数的 dtype 告警/报错(pandas>=2.2)
    out[column] = pd.to_numeric(out[column], errors="coerce").astype(float)
    affected = 0
    for unit, conv in conversions.items():
        mask = out[unit_column].astype(str) == str(unit)
        if not mask.any():
            continue
        factor = float(conv["factor"])
        out.loc[mask, column] = pd.to_numeric(out.loc[mask, column], errors="coerce") * factor
        out.loc[mask, unit_column] = conv["target"]
        affected += int(mask.sum())
    return out, {**base, "affected_rows": affected}


def _require_column(df: pd.DataFrame, column: str | None) -> str:
    if column is None or column not in df.columns:
        raise ValueError(f"列 {column!r} 不存在")
    return column
