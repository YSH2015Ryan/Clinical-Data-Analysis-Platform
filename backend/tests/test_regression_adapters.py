"""T5.5 回归适配器：lasso/elasticnet/rf_reg/xgboost_reg（docs/07 §3、docs/18）。

DoD：4 个适配器全部经 entry_points 注册；合成数据各跑通；
指标由统一 metrics 模块计算（RMSE/MAE/R²，adapter 不自算）。
注：rf/xgboost 分类已占用同名 key（全局唯一约束），回归变体以 _reg 后缀注册。
"""

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.engines.model_registry import ModelRegistry
from sklearn.datasets import make_regression
from sklearn.metrics import mean_squared_error, r2_score

KEYS = ["lasso", "elasticnet", "rf_reg", "xgboost_reg"]


def _regression_data() -> dict[str, Any]:
    X_arr, y = make_regression(
        n_samples=200, n_features=5, n_informative=3, noise=5.0, random_state=42
    )
    X = pd.DataFrame(X_arr, columns=["f1", "f2", "f3", "f4", "f5"])
    return {"X": X, "y": y}


def _load_adapter(key: str) -> Any:
    registry = ModelRegistry()
    registry.load()
    adapter = registry.get(key)
    assert adapter is not None, f"{key} 未经 entry_points 注册"
    return adapter


class TestRegistration:
    @pytest.mark.parametrize("key", KEYS)
    def test_registered_via_entry_points(self, key: str) -> None:
        adapter = _load_adapter(key)
        assert adapter.task_types == ["regression"]
        assert adapter.version

    def test_for_task_includes_all_four(self) -> None:
        registry = ModelRegistry()
        registry.load()
        keys = {a.key for a in registry.for_task("regression")}
        assert set(KEYS) <= keys


class TestEvaluate:
    @pytest.mark.parametrize("key", KEYS)
    def test_recovers_signal(self, key: str) -> None:
        d = _regression_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        assert m["r2"] > 0.9
        assert m["rmse"] > 0.0 and m["mae"] > 0.0
        assert m["mae"] <= m["rmse"]  # RMSE ≥ MAE 恒成立
        json.dumps(m)  # 指标结构可序列化（落库前提）

    @pytest.mark.parametrize("key", KEYS)
    def test_metrics_from_central_module(self, key: str) -> None:
        """adapter 不自算指标：RMSE/R² 与 sklearn 官方实现一致（±1e-6）。"""
        d = _regression_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        pred = adapter._predict(d["X"])
        assert m["rmse"] == pytest.approx(
            float(np.sqrt(mean_squared_error(d["y"], pred))), abs=1e-6
        )
        assert m["r2"] == pytest.approx(r2_score(d["y"], pred), abs=1e-6)


class TestExplain:
    @pytest.mark.parametrize("key", ["lasso", "elasticnet"])
    def test_linear_coefficients(self, key: str) -> None:
        d = _regression_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        assert exp is not None and exp["type"] == "coefficients"
        assert {r["feature"] for r in exp["table"]} == {"f1", "f2", "f3", "f4", "f5"}
        json.dumps(exp)

    @pytest.mark.parametrize("key", ["rf_reg", "xgboost_reg"])
    def test_tree_feature_importance(self, key: str) -> None:
        d = _regression_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        # 树模型走 SHAP 摘要（T5.7）；SHAP 异常时回退内置重要性
        assert exp is not None and exp["type"] in ("shap_summary", "feature_importance")
        assert set(exp["importances"]) == {"f1", "f2", "f3", "f4", "f5"}
        assert max(exp["importances"].values()) > 0.0
        json.dumps(exp)


class TestArtifacts:
    @pytest.mark.parametrize("key", KEYS)
    def test_prediction_scatter(self, key: str) -> None:
        d = _regression_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        art = adapter.predict_artifacts(d["X"], d["y"])
        scatter = art["prediction_scatter"]
        assert len(scatter["y_true"]) == len(scatter["y_pred"]) == len(d["y"])
        json.dumps(art)


class TestProtocolCompliance:
    @pytest.mark.parametrize("key", KEYS)
    def test_fit_with_param_override(self, key: str) -> None:
        d = _regression_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], dict(adapter.default_params))
        m = adapter.evaluate(d["X"], d["y"])
        assert isinstance(m["rmse"], float)
