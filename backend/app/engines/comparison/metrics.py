"""统一指标计算（docs/07 §5）：指标不收在各模型内，模型只输出预测值。

- classification：AUC（主）、Accuracy、Precision、Recall、F1、Brier、PR-AUC
- survival：C-index（主）、IBS（提供生存函数预测时）
- regression：RMSE（主）、MAE、R²

一律调用官方库实现（sklearn / scikit-survival），不自研公式（CLAUDE.md 规则 2；
docs/19：与官方实现对拍 ±1e-6）。
"""

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sksurv.metrics import concordance_index_censored, integrated_brier_score
from sksurv.util import Surv


def _as_float_array(values: Any, name: str) -> np.ndarray[Any, Any]:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} 须为一维数组，当前 shape={arr.shape}")
    return arr


def classification_metrics(y_true: Any, y_prob: Any) -> dict[str, float]:
    """分类指标，兼容二分类正类概率和多分类概率矩阵。"""
    y_t = _as_float_array(y_true, "y_true")
    p = np.asarray(y_prob, dtype=float)
    if p.ndim == 1:
        if y_t.shape[0] != p.shape[0]:
            raise ValueError(f"y_true 与 y_prob 长度不一致：{y_t.shape[0]} vs {p.shape[0]}")
        if not set(np.unique(y_t)) <= {0.0, 1.0}:
            raise ValueError(f"二分类 y_true 仅支持 0/1，当前取值 {np.unique(y_t)!r}")
        y_pred = (p >= 0.5).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_t, y_pred, labels=[0, 1]).ravel()
        sensitivity = float(tp / (tp + fn)) if tp + fn else 0.0
        specificity = float(tn / (tn + fp)) if tn + fp else 0.0
        ppv = float(tp / (tp + fp)) if tp + fp else 0.0
        npv = float(tn / (tn + fn)) if tn + fn else 0.0
        clipped = np.clip(p, 1e-6, 1 - 1e-6)
        logits = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
        calibration_intercept = float("nan")
        calibration_slope = float("nan")
        if len(np.unique(y_t)) == 2:
            from sklearn.linear_model import LogisticRegression

            calibration_model = LogisticRegression(solver="lbfgs").fit(logits, y_t.astype(int))
            calibration_intercept = float(calibration_model.intercept_[0])
            calibration_slope = float(calibration_model.coef_[0, 0])
        return {
            "auc": float(roc_auc_score(y_t, p)),
            "accuracy": float(accuracy_score(y_t, y_pred)),
            "precision": float(precision_score(y_t, y_pred, zero_division=0)),
            "recall": float(recall_score(y_t, y_pred, zero_division=0)),
            "f1": float(f1_score(y_t, y_pred, zero_division=0)),
            "brier": float(brier_score_loss(y_t, p)),
            "pr_auc": float(average_precision_score(y_t, p)),
            "sensitivity": sensitivity,
            "specificity": specificity,
            "ppv": ppv,
            "npv": npv,
            "mcc": float(matthews_corrcoef(y_t.astype(int), y_pred)),
            "calibration_intercept": calibration_intercept,
            "calibration_slope": calibration_slope,
        }
    if p.ndim != 2 or p.shape[0] != y_t.shape[0] or p.shape[1] < 3:
        raise ValueError("多分类 y_prob 须为 shape=(n_samples, n_classes>=3) 的矩阵")
    labels = np.arange(p.shape[1])
    if not set(np.unique(y_t).astype(int)) <= set(labels):
        raise ValueError("y_true 包含超出 y_prob 类别范围的标签")
    y_pred = np.argmax(p, axis=1)
    return {
        "auc": float(roc_auc_score(y_t.astype(int), p, multi_class="ovr", average="macro")),
        "accuracy": float(accuracy_score(y_t, y_pred)),
        "precision_macro": float(precision_score(y_t, y_pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_t, y_pred, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_t, y_pred, average="macro", zero_division=0)),
    }


def regression_metrics(y_true: Any, y_pred: Any, n_features: int | None = None) -> dict[str, float]:
    """回归指标：RMSE（主）、MAE、R²。

    P1-14（updateplan §44）连续结局评价补齐：
    - adjusted_r2：须传 n_features（预测变量数）；n<=p+1 或未传时 NaN（不虚构）；
    - mape：y_true 含 0 时 NaN（§44「适用时」）；
    - mean_bias：回归版 calibration-in-the-large（mean(y_pred-y_true)，系统性偏倚）；
    - calibration_slope：observed ~ predicted OLS 斜率；预测无变异时 NaN。
    """
    y_t = _as_float_array(y_true, "y_true")
    y_p = _as_float_array(y_pred, "y_pred")
    if y_t.shape[0] != y_p.shape[0]:
        raise ValueError(f"y_true 与 y_pred 长度不一致：{y_t.shape[0]} vs {y_p.shape[0]}")
    n = y_t.shape[0]
    r2 = float(r2_score(y_t, y_p))
    adjusted_r2 = float("nan")
    if n_features is not None and n - n_features - 1 > 0:
        adjusted_r2 = float(1.0 - (1.0 - r2) * (n - 1) / (n - n_features - 1))
    mape = float(mean_absolute_percentage_error(y_t, y_p)) if not (y_t == 0).any() else float("nan")
    var_p = float(np.var(y_p))
    calibration_slope = float(np.cov(y_p, y_t, ddof=0)[0, 1] / var_p) if var_p > 0 else float("nan")
    return {
        "rmse": float(np.sqrt(mean_squared_error(y_t, y_p))),
        "mae": float(mean_absolute_error(y_t, y_p)),
        "r2": r2,
        "adjusted_r2": adjusted_r2,
        "mape": mape,
        "mean_bias": float(np.mean(y_p - y_t)),
        "calibration_slope": calibration_slope,
    }


def survival_metrics(
    *,
    event_test: Any,
    time_test: Any,
    risk: Any,
    event_train: Any | None = None,
    time_train: Any | None = None,
    surv_pred: Any | None = None,
    times: Any | None = None,
) -> dict[str, float]:
    """生存指标：C-index（主，risk 越大风险越高）；提供生存函数矩阵时附 IBS。

    surv_pred：shape (n_test, n_times) 的生存概率 S(t|x)；IBS 需要训练集
    （估计删失分布），缺训练集时抛 ValueError。
    IBS 评估前过滤 time_test > max(time_train) 的样本：训练删失 KM 无法外推
    至训练集最大观测时间之后（sksurv 约束）。
    """
    e_test = _as_float_array(event_test, "event_test").astype(bool)
    t_test = _as_float_array(time_test, "time_test")
    r = _as_float_array(risk, "risk")
    if not (e_test.shape[0] == t_test.shape[0] == r.shape[0]):
        raise ValueError("event_test/time_test/risk 长度不一致")

    result = {
        "c_index": float(concordance_index_censored(e_test, t_test, r)[0]),
    }

    if surv_pred is None and times is None:
        return result
    if event_train is None or time_train is None:
        raise ValueError("计算 IBS 须提供训练集 event_train/time_train（估计删失分布）")
    if surv_pred is None or times is None:
        raise ValueError("计算 IBS 须同时提供 surv_pred 与 times")

    e_train = _as_float_array(event_train, "event_train").astype(bool)
    t_train = _as_float_array(time_train, "time_train")
    estimate = np.asarray(surv_pred, dtype=float)

    in_range = t_test <= t_train.max()
    if not in_range.any():
        raise ValueError("IBS 不可计算：全部测试样本时间超出训练集最大观测时间")
    surv_train = Surv.from_arrays(e_train, t_train)
    surv_test = Surv.from_arrays(e_test[in_range], t_test[in_range])
    result["ibs"] = float(integrated_brier_score(surv_train, surv_test, estimate[in_range], times))
    return result
