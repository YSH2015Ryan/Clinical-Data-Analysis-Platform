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
from sklearn.metrics import roc_curve
from sklearn.svm import SVC

from app.engines.comparison.metrics import classification_metrics


def _importances_dict(columns: Any, values: Any) -> dict[str, float]:
    pairs = zip(columns, np.asarray(values, dtype=float), strict=True)
    return {str(col): float(v) for col, v in pairs}


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

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return {"type": "feature_importance", "importances": self._feature_importances()}

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        y = np.asarray(y_val).astype(int)
        prob = self._predict_proba(X_val)
        fpr, tpr, _ = roc_curve(y, prob)
        prob_true, prob_pred = calibration_curve(y, prob, n_bins=10)
        return {
            "roc_curve": {"fpr": fpr.tolist(), "tpr": tpr.tolist()},
            "calibration_curve": {
                "prob_true": prob_true.tolist(),
                "prob_pred": prob_pred.tolist(),
            },
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
        "shap": True,
        "feature_importance": True,
        "calibration": True,
    }
    default_params: ClassVar[dict[str, Any]] = {"n_estimators": 100, "random_state": 42}

    def _build(self, params: dict[str, Any]) -> Any:
        return RandomForestClassifier(**params)


class SvmAdapter(_BaseClassifier):
    """SVM(probability=True)；无内置重要性 → permutation importance 兜底。"""

    key = "svm"
    name = "Support Vector Machine (probability)"
    default_params: ClassVar[dict[str, Any]] = {"probability": True, "random_state": 42}

    def _build(self, params: dict[str, Any]) -> Any:
        return SVC(**params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        result = permutation_importance(self._model, self._X, self._y, n_repeats=5, random_state=42)
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
