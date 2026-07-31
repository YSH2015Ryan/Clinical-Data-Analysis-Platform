"""T5.4 分类适配器：logreg/rf/svm/xgboost/lightgbm/catboost（docs/07 §3、docs/18）。

DoD：6 个适配器全部经 entry_points 注册；合成数据各跑通；概率输出支撑 ROC/校准产物；
指标由统一 metrics 模块计算（adapter 不自算 AUC）。
"""

import json
from typing import Any

import pandas as pd
import pytest
from app.engines.model_registry import ModelRegistry
from sklearn.datasets import make_classification
from sklearn.metrics import roc_auc_score

KEYS = ["logreg", "rf", "svm", "xgboost", "lightgbm", "catboost"]


def _classification_data() -> dict[str, Any]:
    X_arr, y = make_classification(
        n_samples=200,
        n_features=5,
        n_informative=3,
        n_redundant=0,
        n_classes=2,
        random_state=42,
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
        assert "classification" in adapter.task_types
        assert adapter.version

    def test_for_task_includes_all_six(self) -> None:
        registry = ModelRegistry()
        registry.load()
        keys = {a.key for a in registry.for_task("classification")}
        assert set(KEYS) <= keys


class TestEvaluate:
    @pytest.mark.parametrize("key", KEYS)
    def test_recovers_signal(self, key: str) -> None:
        d = _classification_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        assert m["auc"] > 0.85
        for metric in ("accuracy", "precision", "recall", "f1", "brier", "pr_auc"):
            assert 0.0 <= m[metric] <= 1.0, f"{key}.{metric} 越界"
        json.dumps(m)  # 指标结构可序列化（落库前提）

    @pytest.mark.parametrize("key", KEYS)
    def test_metrics_from_central_module(self, key: str) -> None:
        """adapter 不自算指标：AUC 与 sklearn 官方实现一致（±1e-6）。"""
        d = _classification_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        expected = roc_auc_score(d["y"], adapter._predict_proba(d["X"]))
        assert m["auc"] == pytest.approx(expected, abs=1e-6)


class TestExplain:
    def test_logreg_coefficients(self) -> None:
        d = _classification_data()
        adapter = _load_adapter("logreg")
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        assert exp is not None and exp["type"] == "coefficients"
        assert {r["feature"] for r in exp["table"]} == {"f1", "f2", "f3", "f4", "f5"}
        json.dumps(exp)

    @pytest.mark.parametrize("key", ["rf", "xgboost", "lightgbm", "catboost"])
    def test_tree_feature_importance(self, key: str) -> None:
        d = _classification_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        # 树模型走 SHAP 摘要（T5.7）；SHAP 异常时回退内置重要性
        assert exp is not None and exp["type"] in ("shap_summary", "feature_importance")
        assert set(exp["importances"]) == {"f1", "f2", "f3", "f4", "f5"}
        assert max(exp["importances"].values()) > 0.0
        json.dumps(exp)

    def test_svm_permutation_fallback(self) -> None:
        """SVM 无内置重要性 → permutation importance 兜底（docs/07 §6）。"""
        d = _classification_data()
        adapter = _load_adapter("svm")
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        assert exp is not None and exp["type"] == "feature_importance"
        assert set(exp["importances"]) == {"f1", "f2", "f3", "f4", "f5"}


class TestArtifacts:
    @pytest.mark.parametrize("key", KEYS)
    def test_roc_and_calibration(self, key: str) -> None:
        d = _classification_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        art = adapter.predict_artifacts(d["X"], d["y"])
        roc = art["roc_curve"]
        assert len(roc["fpr"]) == len(roc["tpr"]) >= 2
        cal = art["calibration_curve"]
        assert len(cal["prob_true"]) == len(cal["prob_pred"])
        assert all(0.0 <= p <= 1.0 for p in cal["prob_pred"])
        json.dumps(art)


class TestProtocolCompliance:
    @pytest.mark.parametrize("key", KEYS)
    def test_fit_with_param_override(self, key: str) -> None:
        d = _classification_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], dict(adapter.default_params))
        m = adapter.evaluate(d["X"], d["y"])
        assert isinstance(m["auc"], float)
