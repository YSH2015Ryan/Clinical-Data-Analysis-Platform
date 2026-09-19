"""P1-11 缺失数据机制判断（updateplan §12）：MCAR / MAR / MNAR 启发式。

判断逻辑（启发式，非严格因果推断）：
1. 每个有缺失的变量生成 missing_indicator
2. 检验 missing_indicator 与其他已观测变量的关联（卡方 / Mann-Whitney）
3. 检验 missing_indicator 与结局变量的关联
4. 粗略分类：likely_mcar / likely_mar / possible_mnar / undetermined

缺失与结局显著相关 → 固定 WARNING（§12 逐字文案），提示单一插补可能引入偏倚。
默认原则：不静默插补——插补建议按机制分级展示，由研究者确认。

分层纪律：engines 禁止 import fastapi/celery/sqlalchemy。
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from scipy import stats

_MIN_MISSING = 5  # 缺失例数过少 → undetermined（检验无把握度）
_MAX_ASSOC_VARS = 50  # 关联扫描变量数上限（运行时间保护）

# §12 固定 WARNING 文案（{col} 占位；verbatim，非 LLM 生成）
OUTCOME_MISSINGNESS_WARNING = (
    'WARNING: Missingness in "{col}" is associated with the outcome. '
    "Single imputation may introduce bias. "
    "Consider multiple imputation or a missingness-aware model."
)

# §12 插补策略与机制匹配
_IMPUTATION_ADVICE = {
    "likely_mcar": "简单插补（均值/中位数/众数）风险较低。",
    "likely_mar": "建议多重插补（MICE）或基于其他变量的回归插补。",
    "possible_mnar": (
        "任何插补都可能引入系统性偏倚，必须谨慎；建议多重插补或缺失感知模型，并由研究者确认。"
    ),
    "undetermined": "缺失例数过少，机制无法判断；插补前建议人工核查缺失原因。",
}


def _assoc_p(indicator: pd.Series, other: pd.Series) -> float | None:
    """missing_indicator 与另一变量的关联 p：分类 → 卡方/Fisher；连续 → Mann-Whitney。"""
    pair = pd.DataFrame({"i": indicator, "o": other}).dropna()
    if len(pair) < 10 or pair["i"].nunique() < 2:
        return None
    o = pair["o"]
    try:
        if not pd.api.types.is_numeric_dtype(o) or o.nunique(dropna=True) <= 10:
            tbl = pd.crosstab(pair["i"], o)
            if tbl.shape[0] < 2 or tbl.shape[1] < 2:
                return None
            if tbl.shape == (2, 2) and tbl.to_numpy().sum() < 30:
                _, p = stats.fisher_exact(tbl.to_numpy())
            else:
                _, p, _, _ = stats.chi2_contingency(tbl)
            return float(p)
        g1 = o[pair["i"] == 1].to_numpy(dtype=float)
        g0 = o[pair["i"] == 0].to_numpy(dtype=float)
        if len(g1) < 3 or len(g0) < 3:
            return None
        _, p = stats.mannwhitneyu(g1, g0, alternative="two-sided")
        return float(p)
    except Exception:
        return None


def analyze_missingness(
    df: pd.DataFrame,
    *,
    outcome_cols: list[str] | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """逐列缺失机制启发式分类（§12）。

    仅分析缺失数 > 0 的列；outcome_cols 之外的列参与「与其他已观测变量的关联」扫描。
    """
    outcomes = [c for c in (outcome_cols or []) if c in df.columns]
    variables: list[dict[str, Any]] = []
    for col in df.columns:
        if col in outcomes:
            continue
        n_missing = int(df[col].isna().sum())
        if n_missing == 0:
            continue
        indicator = df[col].isna().astype(int)
        entry: dict[str, Any] = {
            "column": str(col),
            "n_missing": n_missing,
            "missing_rate": round(n_missing / len(df), 4) if len(df) else 0.0,
            "outcome_association_p": None,
            "associated_variables": [],
            "mechanism": "undetermined",
            "warning": None,
            "imputation_advice": _IMPUTATION_ADVICE["undetermined"],
        }
        if n_missing < _MIN_MISSING or int((indicator == 0).sum()) < _MIN_MISSING:
            variables.append(entry)
            continue

        # 3. 与结局的关联（任一结局显著即 MNAR 线索）
        outcome_ps = [p for p in (_assoc_p(indicator, df[o]) for o in outcomes) if p is not None]
        outcome_p = min(outcome_ps) if outcome_ps else None
        entry["outcome_association_p"] = outcome_p

        # 2. 与其他已观测变量的关联
        others = [c for c in df.columns if c != col and c not in outcomes][:_MAX_ASSOC_VARS]
        assoc = sorted(
            ((c, p) for c in others if (p := _assoc_p(indicator, df[c])) is not None and p < alpha),
            key=lambda t: t[1],
        )
        entry["associated_variables"] = [c for c, _ in assoc]

        # 4. 分类：结局关联优先（MNAR 风险高于 MAR 证据）
        if outcome_p is not None and outcome_p < alpha:
            entry["mechanism"] = "possible_mnar"
            entry["warning"] = OUTCOME_MISSINGNESS_WARNING.replace("{col}", str(col))
        elif assoc:
            entry["mechanism"] = "likely_mar"
        else:
            entry["mechanism"] = "likely_mcar"
        entry["imputation_advice"] = _IMPUTATION_ADVICE[entry["mechanism"]]
        variables.append(entry)

    variables.sort(key=lambda v: v["missing_rate"], reverse=True)
    return {
        "alpha": alpha,
        "variables": variables,
        "has_outcome_associated_missingness": any(
            v["mechanism"] == "possible_mnar" for v in variables
        ),
    }
