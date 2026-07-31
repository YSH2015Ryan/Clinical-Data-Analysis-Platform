"""内置生存模型插件（docs/07 §3）：km / coxph / rsf / gbs。

- 指标一律经 engines.comparison.metrics 计算，适配器只输出预测值
  （风险分 / 生存函数矩阵），不自算 C-index（docs/07 §5、§7 DoD）；
- y 约定为 sksurv 结构化数组（fields: event[bool], time[float]）；
- IBS 时间网格取训练集时间分位数（05–95），保证删失 KM 可估。
"""

from typing import Any, ClassVar

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, KaplanMeierFitter
from sklearn.inspection import permutation_importance
from sksurv.ensemble import GradientBoostingSurvivalAnalysis, RandomSurvivalForest
from sksurv.util import Surv

from app.engines.comparison.metrics import survival_metrics

_TIME_COL, _EVENT_COL = "__time__", "__event__"


def _split_y(y: Any) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """y → (event, time)；仅接受 sksurv 结构化数组。"""
    arr = np.asarray(y)
    if arr.dtype.names and {"event", "time"} <= set(arr.dtype.names):
        return (
            np.asarray(arr["event"]).astype(bool),
            np.asarray(arr["time"]).astype(float),
        )
    raise ValueError(f"生存任务 y 须为含 event/time 字段的结构化数组，当前 dtype={arr.dtype}")


def _time_grid(train_times: np.ndarray[Any, Any], n: int = 50) -> np.ndarray[Any, Any]:
    """IBS 评估网格：训练时间 5%–95% 分位数（须 ≤ 训练最大观测时间）。"""
    grid: np.ndarray[Any, Any] = np.unique(np.quantile(train_times, np.linspace(0.05, 0.95, n)))
    return grid


def _surv_matrix(step_functions: Any, grid: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """sksurv StepFunction 列表 → (n_samples, n_times) 矩阵。"""
    matrix: np.ndarray[Any, Any] = np.vstack([fn(grid) for fn in step_functions])
    return matrix


class KmAdapter:
    """Kaplan-Meier 总体基线：无协变量，所有样本同一条生存曲线（C-index≈0.5）。"""

    key = "km"
    name = "Kaplan-Meier (population baseline)"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["survival"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": False,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {}

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        event, time = _split_y(y)
        self._train_event, self._train_time = event, time
        self._grid = _time_grid(time)
        self._model = KaplanMeierFitter().fit(durations=time, event_observed=event)

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        event, time = _split_y(y_val)
        n = event.shape[0]
        risk = np.zeros(n)  # 无个体风险区分 → 全 tied
        curve = self._model.survival_function_at_times(self._grid).to_numpy()
        surv_pred = np.tile(curve, (n, 1))
        return survival_metrics(
            event_train=self._train_event,
            time_train=self._train_time,
            event_test=event,
            time_test=time,
            risk=risk,
            surv_pred=surv_pred,
            times=self._grid,
        )

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return None

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        sf = self._model.survival_function_
        ci = self._model.confidence_interval_survival_function_
        return {
            "km_curve": {
                "times": sf.index.to_numpy().tolist(),
                "survival": sf.iloc[:, 0].to_numpy().tolist(),
                "ci_lower": ci.iloc[:, 0].to_numpy().tolist(),
                "ci_upper": ci.iloc[:, 1].to_numpy().tolist(),
            }
        }


class CoxphAdapter:
    """Cox 比例风险（lifelines）；解释产物为系数/HR 表。"""

    key = "coxph"
    name = "Cox Proportional Hazards"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["survival"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": True,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {"penalizer": 0.1}

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        p = {**self.default_params, **params}
        event, time = _split_y(y)
        self._train_event, self._train_time = event, time
        self._grid = _time_grid(time)
        df = pd.DataFrame(X).copy()
        df[_TIME_COL] = time
        df[_EVENT_COL] = event.astype(int)
        self._model = CoxPHFitter(penalizer=p["penalizer"])
        self._model.fit(df, duration_col=_TIME_COL, event_col=_EVENT_COL)

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        event, time = _split_y(y_val)
        risk = self._model.predict_partial_hazard(pd.DataFrame(X_val)).to_numpy()
        surv_pred = (
            self._model.predict_survival_function(pd.DataFrame(X_val), times=self._grid)
            .to_numpy()
            .T
        )
        return survival_metrics(
            event_train=self._train_event,
            time_train=self._train_time,
            event_test=event,
            time_test=time,
            risk=risk,
            surv_pred=surv_pred,
            times=self._grid,
        )

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        summary = self._model.summary
        table = [
            {
                "feature": str(feature),
                "coef": float(row["coef"]),
                "hr": float(row["exp(coef)"]),
                "p_value": float(row["p"]),
            }
            for feature, row in summary.iterrows()
        ]
        return {"type": "coefficients", "table": table}

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return {}


class RsfAdapter:
    """Random Survival Forest（scikit-survival）。

    sksurv RSF 无内置 feature_importances_（NotImplementedError）→
    permutation importance 兜底（docs/07 §6），在训练集上以模型 score(C-index) 计算。
    """

    key = "rsf"
    name = "Random Survival Forest"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["survival"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": True,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "n_estimators": 100,
        "min_samples_split": 10,
        "random_state": 42,
    }

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        p = {**self.default_params, **params}
        event, time = _split_y(y)
        self._train_event, self._train_time = event, time
        self._grid = _time_grid(time)
        self._X = pd.DataFrame(X)
        self._y = Surv.from_arrays(event, time)
        self._model = RandomSurvivalForest(**p)
        self._model.fit(self._X, self._y)

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        event, time = _split_y(y_val)
        risk = np.asarray(self._model.predict(pd.DataFrame(X_val)), dtype=float)
        surv_pred = _surv_matrix(
            self._model.predict_survival_function(pd.DataFrame(X_val)), self._grid
        )
        return survival_metrics(
            event_train=self._train_event,
            time_train=self._train_time,
            event_test=event,
            time_test=time,
            risk=risk,
            surv_pred=surv_pred,
            times=self._grid,
        )

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        result = permutation_importance(self._model, self._X, self._y, n_repeats=5, random_state=42)
        pairs = zip(self._X.columns, result.importances_mean, strict=True)
        importances = {str(col): float(imp) for col, imp in pairs}
        return {"type": "feature_importance", "importances": importances}

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return {}


class GbsAdapter:
    """Gradient Boosting Survival（scikit-survival Cox PH 损失）。"""

    key = "gbs"
    name = "Gradient Boosting Survival"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["survival"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": True,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "n_estimators": 100,
        "learning_rate": 0.1,
        "random_state": 42,
    }

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        p = {**self.default_params, **params}
        event, time = _split_y(y)
        self._train_event, self._train_time = event, time
        self._grid = _time_grid(time)
        self._X = pd.DataFrame(X)
        self._y = Surv.from_arrays(event, time)
        self._model = GradientBoostingSurvivalAnalysis(**p)
        self._model.fit(self._X, self._y)

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        event, time = _split_y(y_val)
        risk = np.asarray(self._model.predict(pd.DataFrame(X_val)), dtype=float)
        surv_pred = _surv_matrix(
            self._model.predict_survival_function(pd.DataFrame(X_val)), self._grid
        )
        return survival_metrics(
            event_train=self._train_event,
            time_train=self._train_time,
            event_test=event,
            time_test=time,
            risk=risk,
            surv_pred=surv_pred,
            times=self._grid,
        )

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        importances = {
            str(col): float(imp)
            for col, imp in zip(self._X.columns, self._model.feature_importances_, strict=True)
        }
        return {"type": "feature_importance", "importances": importances}

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return {}
