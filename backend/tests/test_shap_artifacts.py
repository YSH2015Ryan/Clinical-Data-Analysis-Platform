"""T5.7 SHAP/重要性/图表产物（docs/07 §6、docs/18）。

DoD：树模型出 SHAP 摘要（mean|SHAP| per feature，SHAP 不可用时回退内置重要性）；
Cox 出 HR 森林图数据（hr + 95% CI，与 lifelines summary 一致 ±1e-6）。
"""

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.engines.model_registry import ModelRegistry
from sklearn.datasets import make_classification

TREE_CLASSIFIERS = ["rf", "xgboost", "lightgbm", "catboost"]
TREE_REGRESSORS = ["rf_reg", "xgboost_reg"]


def _classification_data() -> dict[str, Any]:
    X_arr, y = make_classification(
        n_samples=120, n_features=5, n_informative=3, n_redundant=0, random_state=42
    )
    return {"X": pd.DataFrame(X_arr, columns=["f1", "f2", "f3", "f4", "f5"]), "y": y}


def _load_adapter(key: str) -> Any:
    registry = ModelRegistry()
    registry.load()
    adapter = registry.get(key)
    assert adapter is not None
    return adapter


class TestShapSummary:
    @pytest.mark.parametrize("key", TREE_CLASSIFIERS)
    def test_tree_classifier_shap_summary(self, key: str) -> None:
        d = _classification_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        assert exp["type"] == "shap_summary"
        assert exp["method"] == "mean_abs_shap"
        assert set(exp["importances"]) == {"f1", "f2", "f3", "f4", "f5"}
        assert all(v >= 0.0 for v in exp["importances"].values())
        assert max(exp["importances"].values()) > 0.0
        json.dumps(exp)

    def test_shap_fallback_to_builtin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SHAP 计算失败时回退内置 feature_importance（不中断分析）。"""
        import app.plugins.builtin.explain as explain_mod

        def _boom(*args: Any, **kwargs: Any) -> dict[str, float]:
            raise RuntimeError("shap exploded")

        monkeypatch.setattr(explain_mod, "shap_importance", _boom)
        d = _classification_data()
        adapter = _load_adapter("rf")
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        assert exp["type"] == "feature_importance"
        assert max(exp["importances"].values()) > 0.0

    @pytest.mark.parametrize("key", TREE_REGRESSORS)
    def test_tree_regressor_shap_summary(self, key: str) -> None:
        from sklearn.datasets import make_regression

        X_arr, y = make_regression(n_samples=120, n_features=5, noise=5.0, random_state=42)
        X = pd.DataFrame(X_arr, columns=["f1", "f2", "f3", "f4", "f5"])
        adapter = _load_adapter(key)
        adapter.fit(X, y, {})
        exp = adapter.explain(X)
        assert exp["type"] == "shap_summary"
        assert all(v >= 0.0 for v in exp["importances"].values())


class TestCoxHrForest:
    def _cox_data(self) -> dict[str, Any]:
        from sksurv.util import Surv

        rng = np.random.default_rng(42)
        n = 150
        age = rng.normal(60, 10, n)
        treatment = rng.integers(0, 2, n).astype(float)
        X = pd.DataFrame({"age": age, "treatment": treatment})
        linear = 0.05 * age + 1.0 * treatment
        time = rng.exponential(20.0 / np.exp(linear - linear.mean())) + 1.0
        censor = rng.exponential(80.0, n)
        y = Surv.from_arrays(time <= censor, np.minimum(time, censor))
        return {"X": X, "y": y}

    def test_hr_forest_matches_lifelines_summary(self) -> None:
        d = self._cox_data()
        adapter = _load_adapter("coxph")
        adapter.fit(d["X"], d["y"], {})
        art = adapter.predict_artifacts(d["X"], d["y"])
        forest = {r["feature"]: r for r in art["hr_forest"]}
        assert set(forest) == {"age", "treatment"}
        summary = adapter._model.summary
        for feature, row in summary.iterrows():
            assert forest[feature]["hr"] == pytest.approx(row["exp(coef)"], abs=1e-6)
            assert forest[feature]["ci_lower"] == pytest.approx(
                row["exp(coef) lower 95%"], abs=1e-6
            )
            assert forest[feature]["ci_upper"] == pytest.approx(
                row["exp(coef) upper 95%"], abs=1e-6
            )
        assert forest["treatment"]["hr"] > 1.0  # 方向与数据生成一致
        json.dumps(art)
