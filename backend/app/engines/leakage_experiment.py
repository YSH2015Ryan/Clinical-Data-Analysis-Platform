"""§25 Leakage Experiment Mode：A/B/C/D 变量集敏感性实验。

- Model A：全部变量；B：移除可疑泄漏变量（inspect_leakage 发现列）；
  C：移除日期变量；D：仅基线临床变量（确定性启发式：非可疑/非日期/
  非近 ID/非高基数文本的普通测量列）。
- 每集合用固定快速参考模型做 K 折 CV（分类=Logistic、回归=Ridge、
  生存=CoxPH），seed=42，大样本抽样封顶；指标一律调用 sklearn/lifelines
  官方实现（CLAUDE.md 规则 2，不重实现）。
- 解读文案为固定规则模板（A 与 B/C/D 最优集的主指标差分档），数值全部
  真实计算（红线 8），禁止 LLM 生成结论。

分层纪律：engines 禁止 import fastapi/celery/sqlalchemy。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.engines.columns import infer_dtype
from app.engines.leakage import LeakageInspection, inspect_leakage

_SEED = 42
_MAX_ROWS = 5000  # 实验模式为快速敏感性探测，抽样封顶（确定性种子）
_N_SPLITS = 3
_NEAR_ID_UNIQUE_RATIO = 0.9  # 唯一值占比 ≥0.9 视为近 ID，排除出基线集
_DROP_LARGE = 0.10  # 主指标下降 ≥0.10 → 性能很可能由泄漏驱动
_DROP_MODERATE = 0.03  # ≥0.03 → 中等提示

_SET_LABELS = {
    "A_all": "A：全部变量",
    "B_no_suspicious": "B：移除可疑泄漏变量",
    "C_no_dates": "C：移除日期变量",
    "D_baseline": "D：仅基线临床变量",
}

_DATE_NAME_HINTS = ("date", "time", "month", "day", "year", "日期", "时间", "月")


def _outcome_cols(target_col: str, time_col: str | None, event_col: str | None) -> set[str]:
    return {c for c in (target_col, time_col, event_col) if c}


def _suspicious_columns(inspection: LeakageInspection, target_col: str) -> set[str]:
    """泄漏发现涉及的列（去除目标列本身）。"""
    cols: set[str] = set()
    for f in inspection.findings:
        cols.update(c for c in f.columns if c != target_col)
    return cols


def _feature_pool(df: pd.DataFrame, outcome: set[str]) -> list[str]:
    """特征池：结局列/ID/自由文本除外（确定性 dtype 判定）。"""
    pool = []
    for col in df.columns:
        if str(col) in outcome:
            continue
        dtype = infer_dtype(df[col])
        if dtype in ("id", "text"):
            continue
        pool.append(str(col))
    return pool


def plan_variable_sets(
    df: pd.DataFrame,
    *,
    target_col: str,
    time_col: str | None = None,
    event_col: str | None = None,
    inspection: LeakageInspection | None = None,
) -> dict[str, dict[str, Any]]:
    """A/B/C/D 变量集划分（确定性规则，每个集合记录 removed 供报告追溯）。"""
    outcome = _outcome_cols(target_col, time_col, event_col)
    if inspection is None:
        inspection = inspect_leakage(df, target_col=target_col)
    suspicious = _suspicious_columns(inspection, target_col)

    pool = _feature_pool(df, outcome)
    dates = [
        c for c in pool if infer_dtype(df[c]) == "datetime" or _has_date_hint(c)
    ]
    baseline = [
        c
        for c in pool
        if c not in suspicious
        and c not in dates
        and df[c].nunique(dropna=True) / max(len(df), 1) < _NEAR_ID_UNIQUE_RATIO
    ]

    def _entry(key: str, keep: list[str]) -> dict[str, Any]:
        return {
            "set_key": key,
            "label": _SET_LABELS[key],
            "features": keep,
            "removed": sorted(set(pool) - set(keep)),
        }

    b = [c for c in pool if c not in suspicious]
    c_ = [c for c in pool if c not in dates]
    return {
        "A_all": _entry("A_all", pool),
        "B_no_suspicious": _entry("B_no_suspicious", b),
        "C_no_dates": _entry("C_no_dates", c_),
        "D_baseline": _entry("D_baseline", baseline),
    }


def _has_date_hint(name: str) -> bool:
    low = str(name).lower()
    return any(h in low for h in _DATE_NAME_HINTS)


def _design_matrix(df: pd.DataFrame, features: list[str]) -> np.ndarray[Any, Any]:
    """快速实验预处理：数值中位数插补 + 分类哑变量（drop_first）+ 缺失列剔除。

    实验模式只做敏感性对比，不复用完整预处理 DSL；简单确定性管线即可。
    """
    parts: list[pd.DataFrame] = []
    for col in features:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            filled = pd.to_numeric(s, errors="coerce")
            filled = filled.fillna(filled.median() if filled.notna().any() else 0.0)
            parts.append(filled.rename(col).to_frame())
        else:
            dummies = pd.get_dummies(s.astype("string"), prefix=col, drop_first=True)
            if dummies.shape[1] > 0:
                parts.append(dummies.astype(float))
    if not parts:
        return np.empty((len(df), 0))
    return pd.concat(parts, axis=1).to_numpy(dtype=float)


def _cv_fold_indices(n: int, n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """确定性顺序 K 折索引（数据已抽样打乱；seed 纪律见 run_leakage_experiment）。"""
    idx = np.arange(n)
    folds = np.array_split(idx, n_splits)
    return [
        (np.concatenate([folds[j] for j in range(n_splits) if j != i]), folds[i])
        for i in range(n_splits)
    ]


def _oof_predictions(
    x: np.ndarray[Any, Any],
    y: np.ndarray[Any, Any],
    task_type: str,
    df: pd.DataFrame,
    time_col: str | None,
    event_col: str | None,
) -> np.ndarray[Any, Any]:
    """K 折 out-of-fold 预测（分类=概率、回归=预测值、生存=风险分）。"""
    oof = np.zeros(len(y))
    for tr, va in _cv_fold_indices(len(y), _N_SPLITS):
        if task_type == "classification":
            from sklearn.linear_model import LogisticRegression

            model = LogisticRegression(max_iter=1000)
            model.fit(x[tr], y[tr])
            oof[va] = model.predict_proba(x[va])[:, 1]
        elif task_type == "regression":
            from sklearn.linear_model import Ridge

            model = Ridge()
            model.fit(x[tr], y[tr])
            oof[va] = model.predict(x[va])
        else:  # survival：Cox 部分似然风险分
            from lifelines import CoxPHFitter

            assert time_col is not None and event_col is not None
            full = pd.DataFrame(x, columns=[f"_f{i}" for i in range(x.shape[1])])
            full["_t"] = df[time_col].to_numpy(dtype=float)
            full["_e"] = df[event_col].to_numpy(dtype=float)
            cph = CoxPHFitter().fit(full.iloc[tr], duration_col="_t", event_col="_e")
            oof[va] = cph.predict_partial_hazard(full.iloc[va]).to_numpy()
    return oof


def _metrics_for(task_type: str, y: np.ndarray[Any, Any], oof: np.ndarray[Any, Any],
                 df: pd.DataFrame, time_col: str | None, event_col: str | None
                 ) -> dict[str, float]:
    """§25 指标清单：分类=AUC/PR-AUC/Sens/Spec/校准斜率；回归=RMSE/R²；生存=C-index。"""
    if task_type == "classification":
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import average_precision_score, roc_auc_score

        pred = (oof >= 0.5).astype(int)
        pos, neg = y == 1, y == 0
        clipped = np.clip(oof, 1e-6, 1 - 1e-6)
        logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
        slope = (
            float(LogisticRegression(solver="lbfgs").fit(logits, y.astype(int)).coef_[0, 0])
            if len(np.unique(y)) == 2
            else float("nan")
        )
        return {
            "auc": float(roc_auc_score(y, oof)),
            "pr_auc": float(average_precision_score(y, oof)),
            "sensitivity": float((pred[pos] == 1).mean()) if pos.any() else float("nan"),
            "specificity": float((pred[neg] == 0).mean()) if neg.any() else float("nan"),
            "calibration_slope": slope,
        }
    if task_type == "regression":
        from sklearn.metrics import mean_squared_error, r2_score

        return {
            "rmse": float(np.sqrt(mean_squared_error(y, oof))),
            "r2": float(r2_score(y, oof)),
        }
    from lifelines.utils import concordance_index

    assert time_col is not None and event_col is not None
    times = df[time_col].to_numpy(dtype=float)
    events = df[event_col].to_numpy(dtype=bool)
    return {"c_index": float(concordance_index(times, -oof, events))}


_PRIMARY = {"classification": "auc", "regression": "rmse", "survival": "c_index"}


def _interpretation(task_type: str, sets: list[dict[str, Any]]) -> str:
    """固定规则文案（红线 8：只引用真实计算的主指标差）。"""
    primary = _PRIMARY[task_type]
    scored = {s["set_key"]: s["metrics"][primary] for s in sets if s["metrics"]}
    if "A_all" not in scored or len(scored) < 2:
        return "可用变量集不足，无法进行敏感性对比。"
    a = scored["A_all"]
    others = {k: v for k, v in scored.items() if k != "A_all"}
    if task_type == "regression":
        # 回归主指标 RMSE 越小越好：下降 = RMSE 上升量（≥20% 视为大幅）
        best_alt = min(others.values())
        drop = best_alt - a
        magnitude = f"RMSE 由 {a:.4f} 升至 {best_alt:.4f}（+{drop:.4f}）"
        large = drop >= max(abs(a) * 0.2, 1e-9)
        moderate = not large and drop > 0
    else:
        # 分类/生存主指标越大越好：下降 = AUC/C-index 降低量
        best_alt = max(others.values())
        drop = a - best_alt
        magnitude = f"{primary.upper()} 由 {a:.4f} 降至 {best_alt:.4f}（-{drop:.4f}）"
        large = drop >= _DROP_LARGE
        moderate = not large and drop >= _DROP_MODERATE
    if large:
        return (
            f"移除可疑/日期变量后{magnitude}：模型性能大幅下降，"
            "很可能由泄漏驱动（§25）。建议以剔除可疑变量的变量集为准，"
            "并在报告中标注含泄漏变量结果不可解释为真实预测能力。"
        )
    if moderate:
        return (
            f"移除可疑/日期变量后{magnitude}：性能中等下降，"
            "部分性能可能来自可疑变量，建议进一步核查其临床可得性（§25）。"
        )
    return (
        f"移除可疑/日期变量后性能未见明显下降（主指标差 {drop:.4f}）："
        "未发现性能由泄漏驱动的证据（§25）。"
    )


def run_leakage_experiment(
    df: pd.DataFrame,
    *,
    task_type: str,
    target_col: str | None = None,
    label_col: str | None = None,
    time_col: str | None = None,
    event_col: str | None = None,
    inspection: LeakageInspection | None = None,
    max_rows: int = _MAX_ROWS,
) -> dict[str, Any]:
    """执行 A/B/C/D 变量集敏感性实验并给出固定文案解读。

    Raises:
        ValueError: 结局列缺失、任务类型非法或数据量不足以 CV。
    """
    target = target_col or label_col
    if not target or target not in df.columns:
        raise ValueError(f"结局列 {target} 缺失或不在数据集中")
    if task_type == "survival":
        for col in (time_col, event_col):
            if not col or col not in df.columns:
                raise ValueError(f"生存实验需要 time_col 与 event_col（{col} 缺失）")
    if task_type not in _PRIMARY:
        raise ValueError(f"未知任务类型 {task_type}")

    sub = df.copy()
    dropna_cols = [target] + ([time_col, event_col] if task_type == "survival" else [])
    sub = sub.dropna(subset=[str(c) for c in dropna_cols if c])

    # 大样本确定性抽样（实验模式快速探测；seed 纪律）
    if len(sub) > max_rows:
        sub = sub.sample(n=max_rows, random_state=_SEED).reset_index(drop=True)
    if len(sub) < _N_SPLITS * 10:
        raise ValueError(f"样本量 {len(sub)} 不足以进行 {_N_SPLITS} 折交叉验证")

    sets = plan_variable_sets(
        sub, target_col=target, time_col=time_col, event_col=event_col, inspection=inspection
    )

    y = (
        pd.Categorical(sub[target]).codes.astype(float)
        if task_type == "classification"
        else (
            sub[target].to_numpy(dtype=float)
            if task_type == "regression"
            else sub[event_col].to_numpy(dtype=float)  # type: ignore[index]
        )
    )

    results: list[dict[str, Any]] = []
    for key in ("A_all", "B_no_suspicious", "C_no_dates", "D_baseline"):
        entry = sets[key]
        features = entry["features"]
        if not features:
            results.append({**entry, "n_features": 0, "metrics": None,
                            "note": "该集合无可用变量，跳过实验"})
            continue
        x = _design_matrix(sub, features)
        if x.shape[1] == 0:
            results.append({**entry, "n_features": 0, "metrics": None,
                            "note": "该集合变量均不可数值化，跳过实验"})
            continue
        try:
            oof = _oof_predictions(x, y, task_type, sub, time_col, event_col)
            metrics = _metrics_for(task_type, y, oof, sub, time_col, event_col)
            results.append({**entry, "n_features": len(features), "metrics": metrics,
                            "note": None})
        except Exception as exc:
            results.append({**entry, "n_features": len(features), "metrics": None,
                            "note": f"拟合失败：{exc}"})

    return {
        "task_type": task_type,
        "target": target,
        "n_used": len(sub),
        "sets": results,
        "interpretation": _interpretation(task_type, results),
    }
