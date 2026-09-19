"""P1-12 混杂因素校正（updateplan §29）：Multivariable Adjusted Regression。

研究者手动指定候选混杂变量清单——系统不自动猜测因果结构，只按输入执行调整。
按任务类型自动选择模型：classification → Logistic（OR），regression → OLS（β），
survival → Cox（HR）；Unadjusted 与 Adjusted 并列展示（§29 报告要求）。

Principle 4：调整后结果只能称为 Adjusted association，不能称为 Causal effect
（note 文案固定，非 LLM 生成）。

分层纪律：engines 禁止 import fastapi/celery/sqlalchemy。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_MAX_DUMMY_LEVELS = 10  # 分类混杂水平数上限（超出视为高基数，拒绝入模）


def _confounder_matrix(df: pd.DataFrame, confounders: list[str]) -> pd.DataFrame:
    """混杂清单 → 设计矩阵列：连续直取，分类（≤10 水平）哑变量化（drop_first）。"""
    parts: list[pd.DataFrame] = []
    for col in confounders:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s) and s.nunique(dropna=True) > _MAX_DUMMY_LEVELS:
            parts.append(pd.to_numeric(s, errors="coerce").rename(col).to_frame())
            continue
        if s.nunique(dropna=True) > _MAX_DUMMY_LEVELS:
            raise ValueError(
                f"混杂变量 {col} 水平数 {s.nunique(dropna=True)} 超过 {_MAX_DUMMY_LEVELS}，"
                "请先行归并或改用连续形式"
            )
        dummies = pd.get_dummies(s.astype("string"), prefix=col, drop_first=True).astype(float)
        parts.append(dummies)
    return pd.concat(parts, axis=1) if parts else pd.DataFrame(index=df.index)


def _fit_glm(kind: str, y: np.ndarray, x: pd.DataFrame) -> tuple[float, float, float, float]:
    """Logit/OLS 拟合暴露主效应 → (effect, ci_lower, ci_upper, p)；OR/β 尺度。"""
    import statsmodels.api as sm

    design = sm.add_constant(x)
    fit = (sm.Logit(y, design) if kind == "classification" else sm.OLS(y, design)).fit(disp=0)
    beta = float(fit.params["_exposure"])
    lo, hi = (float(v) for v in fit.conf_int().loc["_exposure"])
    p = float(fit.pvalues["_exposure"])
    if kind == "classification":
        return float(np.exp(beta)), float(np.exp(lo)), float(np.exp(hi)), p
    return beta, lo, hi, p


def _fit_cox(
    df: pd.DataFrame, time_col: str, event_col: str, x: pd.DataFrame
) -> tuple[float, float, float, float]:
    """Cox 拟合暴露主效应 → (HR, ci_lower, ci_upper, p)。"""
    from lifelines import CoxPHFitter

    fit_df = pd.concat(
        [
            df[[time_col, event_col]].reset_index(drop=True),
            x.reset_index(drop=True),
        ],
        axis=1,
    )
    cph = CoxPHFitter().fit(fit_df, duration_col=time_col, event_col=event_col)
    coef = float(cph.summary.loc["_exposure", "coef"])
    lo = float(cph.summary.loc["_exposure", "coef lower 95%"])
    hi = float(cph.summary.loc["_exposure", "coef upper 95%"])
    p = float(cph.summary.loc["_exposure", "p"])
    return float(np.exp(coef)), float(np.exp(lo)), float(np.exp(hi)), p


def adjusted_association(
    df: pd.DataFrame,
    *,
    task_type: str,
    exposure: str,
    confounders: list[str],
    label_col: str | None = None,
    time_col: str | None = None,
    event_col: str | None = None,
) -> dict[str, Any]:
    """混杂校正关联分析：Unadjusted vs Adjusted 并列（§29）。

    Raises:
        ValueError: 暴露/混杂/结局列缺失、混杂清单为空或与暴露重复、水平数超限、
            校正模型拟合失败（如完全分离）。
    """
    if not confounders:
        raise ValueError("混杂变量清单为空：请至少指定一个候选混杂变量（§29 由研究者指定）")
    if exposure in confounders:
        raise ValueError(f"混杂变量 {exposure} 不能与暴露变量相同")
    if exposure not in df.columns:
        raise ValueError(f"暴露变量 {exposure} 不在数据集中")
    for col in confounders:
        if col not in df.columns:
            raise ValueError(f"混杂变量 {col} 不在数据集中")

    outcome_cols = [time_col, event_col] if task_type == "survival" else [label_col]
    for col in outcome_cols:
        if not col or col not in df.columns:
            raise ValueError(f"结局列 {col} 缺失或不在数据集中")

    keep = [exposure, *confounders, *[c for c in outcome_cols if c]]
    sub = df[keep].dropna().copy()
    if len(sub) < 30:
        raise ValueError(f"完整病例不足（n={len(sub)} < 30），无法进行多因素校正")

    conf_x = _confounder_matrix(sub, confounders)
    e = (
        pd.to_numeric(sub[exposure], errors="coerce")
        if sub[exposure].nunique() != 2
        else pd.Series(pd.Categorical(sub[exposure]).codes.astype(float), index=sub.index)
    )
    x_unadj = e.rename("_exposure").to_frame()
    x_adj = pd.concat([x_unadj, conf_x], axis=1)

    effect_label = {"classification": "OR", "regression": "β", "survival": "HR"}[task_type]

    def _fit(x: pd.DataFrame) -> dict[str, Any]:
        if task_type == "survival":
            assert time_col is not None and event_col is not None
            effect, lo, hi, p = _fit_cox(sub, time_col, event_col, x)
        else:
            y = (
                pd.Categorical(sub[label_col]).codes.astype(float)
                if task_type == "classification"
                else pd.to_numeric(sub[label_col], errors="coerce").to_numpy(dtype=float)
            )
            effect, lo, hi, p = _fit_glm(task_type, np.asarray(y, dtype=float), x)
        return {
            "effect_label": effect_label,
            "effect": round(effect, 4),
            "ci_lower": round(lo, 4),
            "ci_upper": round(hi, 4),
            "p_value": p,
        }

    try:
        unadjusted = _fit(x_unadj)
    except Exception as exc:
        raise ValueError(f"未校正模型拟合失败：{exc}") from exc
    try:
        adjusted = _fit(x_adj)
    except Exception as exc:
        raise ValueError(f"校正模型拟合失败（可能存在完全分离或共线性）：{exc}") from exc

    return {
        "task_type": task_type,
        "exposure": exposure,
        "confounders": list(confounders),
        "n_used": len(sub),
        "unadjusted": unadjusted,
        "adjusted": adjusted,
        # §29 + Principle 4 固定文案：明确调整清单（无隐藏模型）+ 关联 ≠ 因果
        "note": (
            f"Adjusted association（adjusted for: {', '.join(confounders)}）。"
            "以上为调整后统计关联，不构成因果效应（causal effect）；"
            "残余混杂不能排除，因果结论须依赖研究设计而非统计调整。"
        ),
    }
