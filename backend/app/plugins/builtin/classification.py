"""内置分类模型插件（docs/07 §3）：logreg / rf / svm / xgboost / lightgbm / catboost。

- 指标一律经 engines.comparison.metrics 计算，适配器只输出正类概率（docs/07 §5）；
- 概率输出支撑 ROC / 校准曲线产物（predict_artifacts）；
- SVM 无内置特征重要性 → permutation importance 兜底（docs/07 §6）；
- y 约定为 0/1 二分类数组。
"""

from typing import Any, ClassVar

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, roc_curve
from sklearn.svm import SVC

from app.engines.comparison.metrics import classification_metrics


def _importances_dict(columns: Any, values: Any) -> dict[str, float]:
    pairs = zip(columns, np.asarray(values, dtype=float), strict=True)
    return {str(col): float(v) for col, v in pairs}


def _stratified_subsample(
    X: Any, y: Any, max_rows: int, seed: int = 42
) -> tuple[pd.DataFrame, np.ndarray[Any, Any]]:
    """确定性分层子采样（docs/07 §6.1 大样本保护）；n ≤ max_rows 时原样返回。"""
    X_df = pd.DataFrame(X)
    y_arr = np.asarray(y).astype(int)
    if len(X_df) <= max_rows:
        return X_df, y_arr
    rng = np.random.default_rng(seed)
    take: list[np.ndarray[Any, Any]] = []
    for cls in np.unique(y_arr):
        idx = np.flatnonzero(y_arr == cls)
        k = max(1, round(max_rows * len(idx) / len(y_arr)))
        take.append(rng.choice(idx, size=min(k, len(idx)), replace=False))
    chosen = np.sort(np.concatenate(take))
    return X_df.iloc[chosen], y_arr[chosen]


class _BaseClassifier:
    """分类适配器公共骨架：fit → _build(params)；evaluate 走统一 metrics。"""

    key: str
    name: str
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["classification"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": True,
        "calibration": True,
    }
    default_params: ClassVar[dict[str, Any]] = {}

    def _build(self, params: dict[str, Any]) -> Any:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        p = {**self.default_params, **params}
        self._X = pd.DataFrame(X)
        self._y = np.asarray(y).astype(int)
        self._model = self._build(p)
        self._model.fit(self._X, self._y)

    def _predict_proba(self, X: Any) -> np.ndarray[Any, Any]:
        proba: np.ndarray[Any, Any] = self._model.predict_proba(pd.DataFrame(X))[:, 1]
        return proba

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return classification_metrics(y_val, self._predict_proba(X_val))

    def _feature_importances(self) -> dict[str, float]:
        return _importances_dict(self._X.columns, self._model.feature_importances_)

    def _explain_shap_or_builtin(self, X_val: Any) -> dict[str, Any]:
        """树模型 SHAP 摘要；SHAP 计算失败回退内置重要性（docs/07 §6，不中断分析）。

        大样本保护：mean(|SHAP|) 在 ≤2000 行确定性子样本上估计（docs/07 §6.1）。
        """
        try:
            from app.plugins.builtin.explain import shap_importance

            X_df = pd.DataFrame(X_val)
            if len(X_df) > 2000:
                X_df = X_df.sample(n=2000, random_state=42)
            return {
                "type": "shap_summary",
                "method": "mean_abs_shap",
                "importances": shap_importance(self._model, X_df),
            }
        except Exception:
            return {"type": "feature_importance", "importances": self._feature_importances()}

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return {"type": "feature_importance", "importances": self._feature_importances()}

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        y = np.asarray(y_val).astype(int)
        prob = self._predict_proba(X_val)
        fpr, tpr, thresholds = roc_curve(y, prob)
        prob_true, prob_pred = calibration_curve(y, prob, n_bins=10)
        cm = confusion_matrix(y, (prob >= 0.5).astype(int), labels=[0, 1])
        return {
            "roc_curve": {
                "fpr": fpr.tolist(),
                "tpr": tpr.tolist(),
                # DCA 净获益计算需要（09 §3）；首元素 inf 非合法 JSONB 值 → None
                "thresholds": [float(t) if np.isfinite(t) else None for t in thresholds],
            },
            "calibration_curve": {
                "prob_true": prob_true.tolist(),
                "prob_pred": prob_pred.tolist(),
            },
            "confusion_matrix": {"labels": [0, 1], "matrix": cm.tolist()},
        }


class LogregAdapter(_BaseClassifier):
    key = "logreg"
    name = "Logistic Regression"
    default_params: ClassVar[dict[str, Any]] = {"max_iter": 1000}

    def _build(self, params: dict[str, Any]) -> Any:
        return LogisticRegression(**params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        table = [
            {"feature": str(col), "coef": float(coef)}
            for col, coef in zip(self._X.columns, self._model.coef_[0], strict=True)
        ]
        return {"type": "coefficients", "table": table}


class RfClassifierAdapter(_BaseClassifier):
    key = "rf"
    name = "Random Forest"
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,  # sklearn 森林 SHAP Python 慢路径不可行（docs/07 §6.1）
        "feature_importance": True,
        "calibration": True,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "n_estimators": 100,
        "random_state": 42,
        "n_jobs": -1,  # NFR 4C8G：吃满可用核（T8.3 调优）
    }

    def _build(self, params: dict[str, Any]) -> Any:
        return RandomForestClassifier(**params)

    # explain 继承基类：内置 feature_importances_（docs/07 §6.1）


class SvmAdapter(_BaseClassifier):
    """SVM(probability=True)；无内置重要性 → permutation importance 兜底。

    大样本保护（docs/07 §6.1）：拟合在分层子样本上（max_train_rows，默认 10000）；
    permutation importance 在 ≤2000 行子样本上计算。指标仍在全量验证折计算。
    """

    key = "svm"
    name = "Support Vector Machine (probability)"
    default_params: ClassVar[dict[str, Any]] = {
        "probability": True,
        "random_state": 42,
        "max_train_rows": 10000,
    }

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        p = {**self.default_params, **params}
        max_rows = int(p.pop("max_train_rows"))
        self._X, self._y = _stratified_subsample(X, y, max_rows)
        self._model = self._build(p)
        self._model.fit(self._X, self._y)

    def _build(self, params: dict[str, Any]) -> Any:
        return SVC(**params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        # 训练子样本（≤10k）配对再抽 ≤2k：permutation 需要 (X, y) 对齐
        X_sub, y_sub = _stratified_subsample(self._X, self._y, 2000)
        result = permutation_importance(self._model, X_sub, y_sub, n_repeats=5, random_state=42)
        return {
            "type": "feature_importance",
            "importances": _importances_dict(self._X.columns, result.importances_mean),
        }


class XgboostAdapter(_BaseClassifier):
    key = "xgboost"
    name = "XGBoost"
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": True,
        "feature_importance": True,
        "calibration": True,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "n_estimators": 100,
        "max_depth": 3,
        "random_state": 42,
        "eval_metric": "logloss",
    }

    def _build(self, params: dict[str, Any]) -> Any:
        from xgboost import XGBClassifier

        return XGBClassifier(**params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return self._explain_shap_or_builtin(X_val)


class LightgbmAdapter(_BaseClassifier):
    key = "lightgbm"
    name = "LightGBM"
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": True,
        "feature_importance": True,
        "calibration": True,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "n_estimators": 100,
        "random_state": 42,
        "verbose": -1,
    }

    def _build(self, params: dict[str, Any]) -> Any:
        from lightgbm import LGBMClassifier

        return LGBMClassifier(**params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return self._explain_shap_or_builtin(X_val)


class CatboostAdapter(_BaseClassifier):
    key = "catboost"
    name = "CatBoost"
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": True,
        "feature_importance": True,
        "calibration": True,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "iterations": 100,
        "random_state": 42,
        "verbose": 0,
        "allow_writing_files": False,  # 禁止 catboost_info 落盘
    }

    def _build(self, params: dict[str, Any]) -> Any:
        from catboost import CatBoostClassifier

        return CatBoostClassifier(**params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return self._explain_shap_or_builtin(X_val)
