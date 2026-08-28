"""大样本训练保护（T6.5）：回归/生存任务的确定性分层子采样。

对齐 classification.py 的 `_stratified_subsample`（分类专用，y 为整数标签）；
本模块服务连续 y（回归，分位分箱分层）与结构化 y（生存，按 event 分层）。
指标仍在全量验证折计算，仅拟合侧采样（docs/07 §6.1 同款约定）。
"""

from typing import Any

import numpy as np
import pandas as pd


def stratified_row_subsample(
    X: Any, y: Any, strata: Any, max_rows: int, seed: int = 42
) -> tuple[pd.DataFrame, np.ndarray[Any, Any]]:
    """按 strata 分层确定性子采样；n ≤ max_rows 时原样返回 (DataFrame, ndarray)。

    每层按比例配额（至少 1 行），保证少数类（如生存事件）不被采样吞没。
    """
    X_df = pd.DataFrame(X)
    y_arr = np.asarray(y)
    s = np.asarray(strata)
    if len(X_df) <= max_rows:
        return X_df, y_arr
    rng = np.random.default_rng(seed)
    take: list[np.ndarray[Any, Any]] = []
    for level in np.unique(s):
        idx = np.flatnonzero(s == level)
        k = max(1, round(max_rows * len(idx) / len(s)))
        take.append(rng.choice(idx, size=min(k, len(idx)), replace=False))
    chosen = np.sort(np.concatenate(take))
    return X_df.iloc[chosen], y_arr[chosen]


def regression_strata(y: Any, n_bins: int = 10) -> np.ndarray[Any, Any]:
    """连续 y → 分位分箱编码（回归分层用）；常数列退化为单箱。"""
    series = pd.Series(np.asarray(y, dtype=float))
    if series.nunique() <= 1:
        return np.zeros(len(series), dtype=int)
    codes: np.ndarray[Any, Any] = pd.qcut(
        series, q=min(n_bins, series.nunique()), labels=False, duplicates="drop"
    ).to_numpy()
    return codes
