"""SHAP 摘要计算（docs/07 §6）：树模型 mean(|SHAP|) per feature。

多输出模型（二分类）取正类维度；shap_values 返回结构随 shap 版本变化
（list / (n, features) / (n, features, classes)），统一归一。
"""

from typing import Any

import numpy as np
import pandas as pd


def shap_importance(model: Any, X: pd.DataFrame) -> dict[str, float]:
    """mean(|SHAP|) per feature；调用方负责 try/except 回退内置重要性。"""
    import shap

    explainer = shap.TreeExplainer(model)
    values = explainer.shap_values(X)
    if isinstance(values, list):  # 旧版多输出：取正类
        arr = np.asarray(values[1] if len(values) > 1 else values[0], dtype=float)
    else:
        arr = np.asarray(values, dtype=float)
        if arr.ndim == 3:  # (n_samples, n_features, n_classes)：取正类
            arr = arr[..., 1] if arr.shape[-1] == 2 else arr[..., 0]
    mean_abs = np.abs(arr).mean(axis=0)
    pairs = zip(X.columns, mean_abs, strict=True)
    return {str(col): float(v) for col, v in pairs}
