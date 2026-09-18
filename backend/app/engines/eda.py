"""EDA 引擎（P2-1，docs/08 §3.2 阶段 A）：上传后自动产出的探索性统计。

纯计算、确定性、无 I/O；全部数值真实可溯源（红线 8）。
产出供「数据体检报告」与前端体检卡消费：
- distributions：每列分布（连续→直方图+描述统计；分类→Top 计数）
- missing：逐列缺失率 + 完整病例比例
- correlations：连续列 Pearson 矩阵 + 分类列 Cramér's V 对
- sample_size：行数/事件数/EPV（有 0/1 结局列时）

分层纪律：engines 只依赖 pandas/numpy，禁止 import fastapi/celery/sqlalchemy。
"""

import math
from typing import Any

import numpy as np
import pandas as pd

_HIST_BINS = 10
_TOP_CATEGORIES = 10
_TOP_PAIRS = 10
_MAX_CORR_CONTINUOUS = 30  # 矩阵规模上限（n×n 前端热图可渲染上限）
_MAX_CORR_CATEGORICAL = 20


def _f(x: Any) -> float | None:
    """numpy → 原生 float（JSONB 可序列化）；NaN/inf → None。"""
    if x is None:
        return None
    v = float(x)
    return v if math.isfinite(v) else None


def _distributions(df: pd.DataFrame, profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in profiles:
        name = p["name"]
        if name not in df.columns:
            continue
        s = df[name]
        missing = int(s.isna().sum())
        entry: dict[str, Any] = {
            "name": name,
            "inferred_type": p.get("inferred_type", "unknown"),
            "semantic": p.get("semantic"),
            "missing": missing,
        }
        if p.get("inferred_type") == "continuous":
            v = pd.to_numeric(s, errors="coerce").dropna().to_numpy(dtype=float)
            if len(v) == 0:
                continue
            counts, edges = np.histogram(v, bins=min(_HIST_BINS, max(1, len(np.unique(v)))))
            q1, med, q3 = np.percentile(v, [25, 50, 75])
            mean = float(v.mean())
            std = float(v.std(ddof=1)) if len(v) > 1 else 0.0
            skew = float(((v - mean) ** 3).mean() / (std**3)) if std > 0 and len(v) > 2 else 0.0
            entry.update(
                kind="continuous",
                histogram={"counts": [int(c) for c in counts], "bin_edges": [_f(e) for e in edges]},
                stats={
                    "mean": _f(mean),
                    "std": _f(std),
                    "min": _f(v.min()),
                    "q1": _f(q1),
                    "median": _f(med),
                    "q3": _f(q3),
                    "max": _f(v.max()),
                    "skew": _f(skew),
                },
            )
        else:
            vc = s.astype("string").value_counts().head(_TOP_CATEGORIES)
            entry.update(
                kind="categorical",
                top_counts=[{"value": str(k), "count": int(c)} for k, c in vc.items()],
            )
        out.append(entry)
    return out


def _missing(df: pd.DataFrame, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(df)
    columns = []
    for p in profiles:
        name = p["name"]
        if name not in df.columns:
            continue
        cnt = int(df[name].isna().sum())
        columns.append(
            {"name": name, "missing": cnt, "missing_rate": round(cnt / n, 4) if n else 0.0}
        )
    rows_any = int(df.isna().any(axis=1).sum()) if n and len(df.columns) else 0
    return {
        "columns": sorted(columns, key=lambda c: c["missing_rate"], reverse=True),
        "rows_with_any_missing": rows_any,
        "complete_case_ratio": round((n - rows_any) / n, 4) if n else 0.0,
    }


def _cramers_v(x: pd.Series, y: pd.Series) -> float | None:
    """Cramér's V（无偏修正版，Bergsma 2013）。"""
    from scipy.stats import chi2_contingency

    tbl = pd.crosstab(x, y)
    if tbl.size == 0 or tbl.shape[0] < 2 or tbl.shape[1] < 2:
        return None
    n = float(tbl.to_numpy().sum())
    if n <= 1:
        return None
    chi2 = float(chi2_contingency(tbl, correction=False)[0])
    r, k = tbl.shape
    phi2 = max(0.0, chi2 / n - (k - 1) * (r - 1) / (n - 1))
    r_adj = r - (r - 1) ** 2 / (n - 1)
    k_adj = k - (k - 1) ** 2 / (n - 1)
    denom = min(k_adj - 1, r_adj - 1)
    return math.sqrt(phi2 / denom) if denom > 0 else None


def _correlations(df: pd.DataFrame, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    cont = [
        p["name"]
        for p in profiles
        if p.get("inferred_type") == "continuous" and p["name"] in df.columns
    ]
    cont = cont[:_MAX_CORR_CONTINUOUS]
    cont_out: dict[str, Any] = {"columns": cont, "matrix": [], "top_pairs": []}
    if cont:
        mat = df[cont].apply(pd.to_numeric, errors="coerce").corr(method="pearson")
        matrix = [[_f(v) for v in row] for row in mat.to_numpy()]
        cont_out["matrix"] = matrix
        pairs = []
        for i in range(len(cont)):
            for j in range(i + 1, len(cont)):
                r = matrix[i][j]
                if r is not None:
                    pairs.append({"a": cont[i], "b": cont[j], "r": round(r, 4)})
        cont_out["top_pairs"] = sorted(pairs, key=lambda p: abs(p["r"]), reverse=True)[:_TOP_PAIRS]

    cat = [
        p["name"]
        for p in profiles
        if p.get("inferred_type") in ("categorical",) and p["name"] in df.columns
    ]
    cat = cat[:_MAX_CORR_CATEGORICAL]
    cat_pairs = []
    for i in range(len(cat)):
        for j in range(i + 1, len(cat)):
            v = _cramers_v(df[cat[i]].astype("string"), df[cat[j]].astype("string"))
            if v is not None:
                cat_pairs.append({"a": cat[i], "b": cat[j], "cramers_v": round(v, 4)})
    cat_out = {
        "columns": cat,
        "top_pairs": sorted(cat_pairs, key=lambda p: p["cramers_v"], reverse=True)[:_TOP_PAIRS],
    }
    return {"continuous": cont_out, "categorical": cat_out}


def _sample_size(df: pd.DataFrame, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """样本量/事件数/EPV：取 semantic 为 Event/Label 且 0/1 二值的首列。"""
    event_col: str | None = None
    for p in profiles:
        if p.get("semantic") in ("Event", "Label") and p.get("unique") == 2:
            event_col = p["name"]
            break
    n_events: int | None = None
    epv: float | None = None
    n_features = max(0, len(profiles) - 1)
    if event_col is not None and event_col in df.columns and n_features > 0:
        s = pd.to_numeric(df[event_col], errors="coerce")
        n_events = int((s == 1).sum())
        epv = round(n_events / n_features, 2)
    # updateplan §19（P0-11）三档：≥10 ok / 5–10 warning / <5 critical
    epv_level: str | None = None
    if epv is not None:
        epv_level = "ok" if epv >= 10 else ("warning" if epv >= 5 else "critical")
    return {
        "n_rows": len(df),
        "n_features": n_features,
        "event_column": event_col,
        "n_events": n_events,
        "epv": epv,
        "epv_level": epv_level,
        "epv_adequate": (epv is not None and epv >= 10) or None,
    }


def compute_eda(df: pd.DataFrame, column_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """计算 EDA 汇总（确定性；同输入恒同输出）。"""
    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "distributions": _distributions(df, column_profiles),
        "missing": _missing(df, column_profiles),
        "correlations": _correlations(df, column_profiles),
        "sample_size": _sample_size(df, column_profiles),
    }
