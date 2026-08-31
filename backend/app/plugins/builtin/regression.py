"""内置回归模型插件（docs/07 §3）：lasso / elasticnet / rf_reg / xgboost_reg。

- 指标一律经 engines.comparison.metrics 计算（RMSE/MAE/R²），适配器只输出预测值；
- rf/xgboost 的分类同名 key 已被占用（注册表 key 全局唯一），回归变体以 _reg 后缀注册；
- 产物：预测值-真实值散点数据（prediction_scatter）。
"""

from typing import Any, ClassVar

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import ElasticNet, Lasso

from app.engines.comparison.metrics import regression_metrics
from app.plugins.builtin.classification import _importances_dict
from app.plugins.builtin.sampling import regression_strata, stratified_row_subsample


def _subsampled_fit(adapter: Any, X: Any, y: Any, params: dict[str, Any]) -> None:
    """大样本保护（T6.5，对齐分类插件）：连续 y 分位分箱分层采样后拟合。"""
    p = {**adapter.default_params, **params}
    max_rows = int(p.pop("max_train_rows"))
    y_arr = np.asarray(y, dtype=float)
    adapter._X, adapter._y = stratified_row_subsample(X, y_arr, regression_strata(y_arr), max_rows)
    adapter._model = adapter._build(p)
    adapter._model.fit(adapter._X, adapter._y)


class _BaseRegressor:
    """回归适配器公共骨架：fit → _build(params)；evaluate 走统一 metrics。"""

    key: str
    name: str
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["regression"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": True,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {}

    def _build(self, params: dict[str, Any]) -> Any:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        p = {**self.default_params, **params}
        self._X = pd.DataFrame(X)
        self._y = np.asarray(y, dtype=float)
        self._model = self._build(p)
        self._model.fit(self._X, self._y)

    def _predict(self, X: Any) -> np.ndarray[Any, Any]:
        pred: np.ndarray[Any, Any] = self._model.predict(pd.DataFrame(X))
        return pred

    def predict_values(self, X: Any) -> np.ndarray[Any, Any]:
        return self._predict(X)

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return regression_metrics(y_val, self._predict(X_val))

    def _explain_shap_or_builtin(self, X_val: Any) -> dict[str, Any]:
        """树模型 SHAP 摘要；SHAP 计算失败回退内置重要性（docs/07 §6）。"""
        try:
            from app.plugins.builtin.explain import shap_importance

            return {
                "type": "shap_summary",
                "method": "mean_abs_shap",
                "importances": shap_importance(self._model, pd.DataFrame(X_val)),
            }
        except Exception:
            return self._builtin_importance()

    def _builtin_importance(self) -> dict[str, Any]:
        return {
            "type": "feature_importance",
            "importances": _importances_dict(self._X.columns, self._model.feature_importances_),
        }

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return self._builtin_importance()

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        pred = self._predict(X_val)
        artifacts = self.predict_artifacts_from_predictions(pred, y_val)

        # 添加诊断所需的残差和特征矩阵
        y_true = np.asarray(y_val, dtype=float)
        y_pred = np.asarray(pred, dtype=float)
        residuals = y_true - y_pred

        artifacts["diagnostic_data"] = {
            "residuals": residuals.tolist(),
            "X": np.asarray(X_val, dtype=float).tolist() if hasattr(X_val, "tolist") else None,
        }

        return artifacts

    def predict_artifacts_from_predictions(self, pred: Any, y_val: Any) -> dict[str, Any]:
        return {
            "prediction_scatter": {
                "y_true": np.asarray(y_val, dtype=float).tolist(),
                "y_pred": np.asarray(pred, dtype=float).tolist(),
            }
        }


class LassoAdapter(_BaseRegressor):
    key = "lasso"
    name = "LASSO"
    # selection='random' 在大特征集上比 'cyclic' 快 3-10x；tol=1e-3 放宽收敛以避免满迭代
    default_params: ClassVar[dict[str, Any]] = {
        "alpha": 0.01,
        "max_iter": 2000,
        "tol": 1e-3,
        "selection": "random",
        "random_state": 42,
    }

    def _build(self, params: dict[str, Any]) -> Any:
        return Lasso(**params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        table = [
            {"feature": str(col), "coef": float(coef)}
            for col, coef in zip(self._X.columns, self._model.coef_, strict=True)
        ]
        return {"type": "coefficients", "table": table}


class ElasticnetAdapter(_BaseRegressor):
    key = "elasticnet"
    name = "ElasticNet"
    # selection='random' 同上；tol 放宽收敛
    default_params: ClassVar[dict[str, Any]] = {
        "alpha": 0.01,
        "l1_ratio": 0.5,
        "max_iter": 2000,
        "tol": 1e-3,
        "selection": "random",
        "random_state": 42,
    }

    def _build(self, params: dict[str, Any]) -> Any:
        return ElasticNet(**params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        table = [
            {"feature": str(col), "coef": float(coef)}
            for col, coef in zip(self._X.columns, self._model.coef_, strict=True)
        ]
        return {"type": "coefficients", "table": table}


class RfRegressorAdapter(_BaseRegressor):
    key = "rf_reg"
    name = "Random Forest (regression)"
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,  # sklearn 森林 SHAP Python 慢路径不可行（docs/07 §6.1）
        "feature_importance": True,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "n_estimators": 100,
        "random_state": 42,
        "n_jobs": 2,  # 限制并发线程数：chord 多模型并行时防内存爆炸（hotfix 4b45c3a 实测）
        "max_train_rows": 100000,  # T6.5：森林内存随行数线性增长,10 万行封顶采样
    }

    def _build(self, params: dict[str, Any]) -> Any:
        return RandomForestRegressor(**params)

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        _subsampled_fit(self, X, y, params)

    # sklearn 森林：SHAP Python 慢路径不可行 → 内置重要性（docs/07 §6.1）；继承基类 explain


class XgboostRegressorAdapter(_BaseRegressor):
    key = "xgboost_reg"
    name = "XGBoost (regression)"
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": True,
        "feature_importance": True,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "n_estimators": 100,
        "max_depth": 3,
        "random_state": 42,
        "n_jobs": -1,  # T6.5：吃满可用核
        "max_train_rows": 200000,  # T6.5：大样本保护
    }

    def _build(self, params: dict[str, Any]) -> Any:
        from xgboost import XGBRegressor

        return XGBRegressor(**params)

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        _subsampled_fit(self, X, y, params)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return self._explain_shap_or_builtin(X_val)
