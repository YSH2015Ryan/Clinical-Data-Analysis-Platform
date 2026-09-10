"""单因素筛选 + 亚组分析（T6.10）。

单因素筛选：逐特征与结局的关联检验（分类=Mann-Whitney/Fisher/卡方，
生存=单因素 Cox，回归=Pearson 相关/单因素方差分析），p<alpha 入选供多因素建模。
亚组分析：按亚组变量分层估计暴露效应（OR/HR/β + 95%CI）+ 交互作用 LRT p 值。

所有统计量由 scipy/statsmodels/lifelines 真实计算，不虚构（红线8）。
分层纪律：engines 禁止 import fastapi/celery/sqlalchemy。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import stats

_MAX_FEATURES = 50  # 单次筛选特征上限（运行时间保护）
_MAX_SUBGROUP_LEVELS = 6  # 亚组变量水平数上限
_MIN_LEVEL_N = 10  # 亚组每层最小样本量（不足则该层效应不可估计）


def _is_categorical(series: pd.Series) -> bool:
    return not pd.api.types.is_numeric_dtype(series) or series.nunique(dropna=True) <= 10


def _binary_codes(series: pd.Series) -> NDArray[np.float64]:
    return pd.Categorical(series).codes.astype(float)


# ---------------------------------------------------------------- 单因素筛选


def _screen_classification(
    df: pd.DataFrame, feature: str, y: NDArray[np.float64]
) -> dict[str, Any] | None:
    pair = df[[feature]].copy()
    pair["_y"] = y
    pair = pair.dropna()
    if len(pair) < 10 or pair["_y"].nunique() < 2:
        return None
    x = pair[feature]
    yy = pair["_y"].to_numpy()
    if not _is_categorical(x):
        x_pos = x[yy == 1].to_numpy(dtype=float)
        x_neg = x[yy == 0].to_numpy(dtype=float)
        if len(x_pos) < 3 or len(x_neg) < 3 or np.all(x == x.iloc[0]):
            return None
        stat, p = stats.mannwhitneyu(x_pos, x_neg, alternative="two-sided")
        return {
            "feature": feature,
            "test": "Mann-Whitney U",
            "statistic": round(float(stat), 4),
            "effect": round(float(np.median(x_pos) - np.median(x_neg)), 4),
            "p_value": float(p),
            "n_used": len(pair),
        }
    table = pd.crosstab(x, yy)
    if table.shape[0] < 2:
        return None
    chi2_val: float | None = None
    stat_val: float | None = None
    if table.shape == (2, 2):
        _, p = stats.fisher_exact(table.to_numpy())
        test = "Fisher 精确检验"
    else:
        chi2_val, p, _, _ = stats.chi2_contingency(table)
        stat_val, test = float(chi2_val), "卡方检验"
    n = table.to_numpy().sum()
    cramers_v = (
        float(np.sqrt(chi2_val / (n * (min(table.shape) - 1)))) if chi2_val is not None else None
    )
    return {
        "feature": feature,
        "test": test,
        "statistic": round(stat_val, 4) if stat_val is not None else None,
        "effect": round(cramers_v, 4) if cramers_v is not None else None,
        "p_value": float(p),
        "n_used": len(pair),
    }


def _screen_survival(
    df: pd.DataFrame, feature: str, time_col: str, event_col: str
) -> dict[str, Any] | None:
    from lifelines import CoxPHFitter

    cols = [time_col, event_col, feature]
    sub = df[cols].dropna()
    if len(sub) < 20 or sub[event_col].sum() < 5:
        return None
    x = sub[feature]
    if _is_categorical(x) and x.nunique() > 1:
        dummies = pd.get_dummies(x, prefix=feature, drop_first=True).astype(float)
        fit_df = pd.concat(
            [sub[[time_col, event_col]].reset_index(drop=True), dummies.reset_index(drop=True)],
            axis=1,
        )
    elif pd.api.types.is_numeric_dtype(x):
        if x.nunique() < 2:
            return None
        fit_df = sub[[time_col, event_col, feature]].copy()
    else:
        return None
    try:
        cph = CoxPHFitter()
        cph.fit(fit_df, duration_col=time_col, event_col=event_col)
        k = fit_df.shape[1] - 2
        if k > 1:
            # 多水平分类：整体 LRT（对数似然 vs 零模型）
            lrt = 2 * (cph.log_likelihood_ - cph.log_likelihood_null_)
            p = float(stats.chi2.sf(lrt, k - 1))
            stat: float | None = round(float(lrt), 4)
            test = "单因素 Cox(LRT)"
        else:
            p = float(cph.summary["p"].iloc[0])
            coef = float(cph.summary["coef"].iloc[0])
            se = float(cph.summary["se(coef)"].iloc[0])
            stat = round(coef / se, 4) if se > 0 else None
            test = "单因素 Cox"
        hr = float(np.exp(cph.summary["coef"].iloc[0]))
        return {
            "feature": feature,
            "test": test,
            "statistic": stat,
            "effect": round(hr, 4),
            "p_value": p,
            "n_used": len(sub),
        }
    except Exception:
        return None


def _screen_regression(df: pd.DataFrame, feature: str, y: pd.Series) -> dict[str, Any] | None:
    pair = pd.DataFrame({"x": df[feature], "y": y}).dropna()
    if len(pair) < 10 or pair["y"].nunique() < 2:
        return None
    x = pair["x"]
    if not _is_categorical(x):
        if x.nunique() < 2:
            return None
        r, p = stats.pearsonr(x.to_numpy(dtype=float), pair["y"].to_numpy(dtype=float))
        return {
            "feature": feature,
            "test": "Pearson 相关",
            "statistic": None,
            "effect": round(float(r), 4),
            "p_value": float(p),
            "n_used": len(pair),
        }
    groups = [g["y"].to_numpy(dtype=float) for _, g in pair.groupby("x") if len(g) >= 2]
    if len(groups) < 2:
        return None
    f_stat, p = stats.f_oneway(*groups)
    grand = pair["y"].to_numpy(dtype=float)
    ss_between = sum(len(g) * (g.mean() - grand.mean()) ** 2 for g in groups)
    ss_total = float(((grand - grand.mean()) ** 2).sum())
    eta2 = float(ss_between / ss_total) if ss_total > 0 else None
    return {
        "feature": feature,
        "test": "单因素方差分析",
        "statistic": round(float(f_stat), 4),
        "effect": round(eta2, 4) if eta2 is not None else None,
        "p_value": float(p),
        "n_used": len(pair),
    }


def univariate_screen(
    df: pd.DataFrame,
    *,
    task_type: str,
    label_col: str | None = None,
    time_col: str | None = None,
    event_col: str | None = None,
    features: list[str] | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """单因素筛选：逐特征关联检验，p<alpha 入选（供多因素建模）。

    Raises:
        ValueError: 结局列缺失或不在数据集中。
    """
    outcome_cols: list[str]
    t_col: str | None = None
    e_col: str | None = None
    if task_type == "survival":
        if not time_col or not event_col:
            raise ValueError("生存分析筛选需要 time_col 与 event_col")
        for col in (time_col, event_col):
            if col not in df.columns:
                raise ValueError(f"结局列 {col} 不在数据集中")
        t_col, e_col = time_col, event_col
        outcome_cols = [t_col, e_col]
    else:
        if not label_col:
            raise ValueError("分类/回归筛选需要 label_col")
        if label_col not in df.columns:
            raise ValueError(f"结局列 {label_col} 不在数据集中")
        outcome_cols = [label_col]

    candidates = features or [str(c) for c in df.columns if str(c) not in outcome_cols]
    candidates = [c for c in candidates if c in df.columns and c not in outcome_cols][
        :_MAX_FEATURES
    ]

    rows: list[dict[str, Any]] = []
    for feature in candidates:
        if task_type == "classification":
            y = _binary_codes(df[label_col])
            row = _screen_classification(df, feature, y)
        elif task_type == "survival":
            assert t_col is not None and e_col is not None  # 上文已校验
            row = _screen_survival(df, feature, t_col, e_col)
        else:
            row = _screen_regression(df, feature, pd.to_numeric(df[label_col], errors="coerce"))
        if row is not None:
            row["selected"] = bool(row["p_value"] < alpha)
            rows.append(row)

    rows.sort(key=lambda r: r["p_value"])
    return {
        "task_type": task_type,
        "alpha": alpha,
        "rows": rows,
        "selected_features": [r["feature"] for r in rows if r["selected"]],
    }


# ---------------------------------------------------------------- 亚组分析


def _or_2x2(sub: pd.DataFrame, exposure: str, y: NDArray[np.float64]) -> tuple[float, float, float]:
    """二分类暴露 × 二分类结局 → OR（log 法 95%CI；零格加 0.5 连续性校正）。"""
    codes = _binary_codes(sub[exposure])
    a = float(((codes == 1) & (y == 1)).sum())
    b = float(((codes == 1) & (y == 0)).sum())
    c = float(((codes == 0) & (y == 1)).sum())
    d = float(((codes == 0) & (y == 0)).sum())
    if min(a, b, c, d) == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    or_ = (a * d) / (b * c)
    se = float(np.sqrt(1 / a + 1 / b + 1 / c + 1 / d))
    lo = float(np.exp(np.log(or_) - 1.96 * se))
    hi = float(np.exp(np.log(or_) + 1.96 * se))
    return float(or_), lo, hi


def _design_matrices(
    sub: pd.DataFrame, exposure: str, subgroup: str, y: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64], int]:
    """暴露 + 亚组哑变量（reduced）与 + 交互项（full）的设计矩阵；返回 (X_red, X_full, k_inter)。"""
    e = pd.to_numeric(sub[exposure], errors="coerce").to_numpy(dtype=float)
    if _binary_codes(sub[exposure]).max() == 1 and sub[exposure].nunique() == 2:
        e = _binary_codes(sub[exposure])
    dummies = pd.get_dummies(sub[subgroup], drop_first=True).astype(float).to_numpy()
    intercept = np.ones((len(sub), 1))
    x_red = np.hstack([intercept, e.reshape(-1, 1), dummies])
    inter = dummies * e.reshape(-1, 1)
    x_full = np.hstack([x_red, inter])
    return x_red, x_full, dummies.shape[1]


def _interaction_p_glm(
    sub: pd.DataFrame, exposure: str, subgroup: str, y: NDArray[np.float64], kind: str
) -> float | None:
    """分类/回归交互作用 LRT p（statsmodels Logit/OLS）。"""
    import statsmodels.api as sm

    x_red, x_full, k = _design_matrices(sub, exposure, subgroup, y)
    if k < 1:
        return None
    try:
        if kind == "classification":
            m_red = sm.Logit(y, x_red).fit(disp=0)
            m_full = sm.Logit(y, x_full).fit(disp=0)
        else:
            m_red = sm.OLS(y, x_red).fit()
            m_full = sm.OLS(y, x_full).fit()
        lrt = 2 * (m_full.llf - m_red.llf)
        return float(stats.chi2.sf(max(lrt, 0.0), k))
    except Exception:
        return None


def _interaction_p_cox(
    sub: pd.DataFrame, exposure: str, subgroup: str, time_col: str, event_col: str
) -> float | None:
    """生存交互作用 LRT p（lifelines Cox 全模型 vs 无交互）。"""
    from lifelines import CoxPHFitter

    dummies = pd.get_dummies(sub[subgroup], drop_first=True).astype(float)
    if dummies.shape[1] < 1:
        return None
    e = (
        _binary_codes(sub[exposure])
        if sub[exposure].nunique() == 2
        else pd.to_numeric(sub[exposure], errors="coerce").to_numpy(dtype=float)
    )
    base = sub[[time_col, event_col]].reset_index(drop=True).copy()
    base["_e"] = e
    red = pd.concat([base, dummies.reset_index(drop=True)], axis=1)
    inter = dummies.mul(e, axis=0)
    inter.columns = [f"_ix_{c}" for c in dummies.columns]
    full = pd.concat([red, inter.reset_index(drop=True)], axis=1)
    try:
        m_red = CoxPHFitter().fit(red, duration_col=time_col, event_col=event_col)
        m_full = CoxPHFitter().fit(full, duration_col=time_col, event_col=event_col)
        lrt = 2 * (m_full.log_likelihood_ - m_red.log_likelihood_)
        return float(stats.chi2.sf(max(lrt, 0.0), dummies.shape[1]))
    except Exception:
        return None


def _level_effect(
    sub: pd.DataFrame,
    *,
    task_type: str,
    exposure: str,
    label_col: str | None,
    time_col: str | None,
    event_col: str | None,
) -> tuple[float | None, float | None, float | None, str | None]:
    """单亚组内暴露效应估计（OR/HR/β + 95%CI）；失败 → (None×3, 原因)。"""
    if len(sub) < _MIN_LEVEL_N:
        return None, None, None, f"样本量 {len(sub)} < {_MIN_LEVEL_N}，效应不可稳定估计"
    try:
        if task_type == "classification":
            y = _binary_codes(sub[label_col])
            if len(np.unique(y)) < 2:
                return None, None, None, "该亚组结局无变异"
            if sub[exposure].nunique() == 2:
                or_, lo, hi = _or_2x2(sub, exposure, y)
                return round(or_, 4), round(lo, 4), round(hi, 4), None
            import statsmodels.api as sm

            e = pd.to_numeric(sub[exposure], errors="coerce").to_numpy(dtype=float)
            x = sm.add_constant(e)
            fit = sm.Logit(y, x).fit(disp=0)
            beta, ci = fit.params[1], fit.conf_int()[1]
            return (
                round(float(np.exp(beta)), 4),
                round(float(np.exp(ci[0])), 4),
                round(float(np.exp(ci[1])), 4),
                None,
            )
        if task_type == "survival":
            from lifelines import CoxPHFitter

            e = (
                _binary_codes(sub[exposure])
                if sub[exposure].nunique() == 2
                else pd.to_numeric(sub[exposure], errors="coerce").to_numpy(dtype=float)
            )
            fit_df = pd.DataFrame(
                {"_t": sub[time_col].to_numpy(), "_e": sub[event_col].to_numpy(), "_x": e}
            )
            cph = CoxPHFitter().fit(fit_df, duration_col="_t", event_col="_e")
            coef = float(cph.summary["coef"].iloc[0])
            lo = float(cph.summary["coef lower 95%"].iloc[0])
            hi = float(cph.summary["coef upper 95%"].iloc[0])
            return (
                round(float(np.exp(coef)), 4),
                round(float(np.exp(lo)), 4),
                round(float(np.exp(hi)), 4),
                None,
            )
        import statsmodels.api as sm

        y = pd.to_numeric(sub[label_col], errors="coerce").to_numpy(dtype=float)
        e = pd.to_numeric(sub[exposure], errors="coerce").to_numpy(dtype=float)
        fit = sm.OLS(y, sm.add_constant(e)).fit()
        beta, ci = fit.params[1], fit.conf_int()[1]
        return round(float(beta), 4), round(float(ci[0]), 4), round(float(ci[1]), 4), None
    except Exception as exc:
        return None, None, None, f"拟合失败：{exc}"


def subgroup_analysis(
    df: pd.DataFrame,
    *,
    task_type: str,
    exposure: str,
    subgroup_vars: list[str],
    label_col: str | None = None,
    time_col: str | None = None,
    event_col: str | None = None,
) -> dict[str, Any]:
    """亚组分析：分层暴露效应（OR/HR/β + 95%CI）+ 暴露×亚组交互 LRT p。

    Raises:
        ValueError: 暴露/亚组/结局列缺失，或亚组变量水平数非法。
    """
    if exposure not in df.columns:
        raise ValueError(f"暴露变量 {exposure} 不在数据集中")
    outcome_cols = [time_col, event_col] if task_type == "survival" else [label_col]
    for col in outcome_cols:
        if not col or col not in df.columns:
            raise ValueError(f"结局列 {col} 缺失或不在数据集中")
    t_col = time_col if task_type == "survival" else None
    e_col = event_col if task_type == "survival" else None
    assert task_type != "survival" or (t_col is not None and e_col is not None)

    results: list[dict[str, Any]] = []
    for var in subgroup_vars:
        if var not in df.columns:
            raise ValueError(f"亚组变量 {var} 不在数据集中")
        if var == exposure:
            raise ValueError(f"亚组变量 {var} 不能与暴露变量相同")
        n_levels = int(df[var].nunique(dropna=True))
        if not 2 <= n_levels <= _MAX_SUBGROUP_LEVELS:
            raise ValueError(
                f"亚组变量 {var} 水平数为 {n_levels}，需 2-{_MAX_SUBGROUP_LEVELS} 个分类水平"
            )
        keep = [var, exposure, *[c for c in outcome_cols if c]]
        sub_all = df[keep].dropna().copy()
        sub_all[var] = sub_all[var].astype(str)

        levels: list[dict[str, Any]] = []
        for level, sub in sub_all.groupby(var):
            effect, lo, hi, note = _level_effect(
                sub,
                task_type=task_type,
                exposure=exposure,
                label_col=label_col,
                time_col=time_col,
                event_col=event_col,
            )
            levels.append(
                {
                    "level": str(level),
                    "n": len(sub),
                    "effect": effect,
                    "ci_lower": lo,
                    "ci_upper": hi,
                    "note": note,
                }
            )

        if task_type == "survival":
            assert t_col is not None and e_col is not None  # 上文已校验
            interaction_p = _interaction_p_cox(sub_all, exposure, var, t_col, e_col)
        else:
            y = (
                _binary_codes(sub_all[label_col])
                if task_type == "classification"
                else pd.to_numeric(sub_all[label_col], errors="coerce").to_numpy(dtype=float)
            )
            interaction_p = _interaction_p_glm(sub_all, exposure, var, y, task_type)

        results.append({"variable": var, "levels": levels, "interaction_p": interaction_p})

    return {"task_type": task_type, "exposure": exposure, "subgroups": results}
