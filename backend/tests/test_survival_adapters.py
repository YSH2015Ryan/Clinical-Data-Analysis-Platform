"""T5.3 生存适配器：km/coxph/rsf/gbs（docs/07 §3、docs/18）。

DoD：4 个适配器全部经 entry_points 注册（核心零特殊处理）；合成数据各跑通；
指标由统一 metrics 模块计算（adapter 不自算 C-index）；结构正确可 JSON 序列化。
"""

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.engines.model_registry import ModelRegistry
from sksurv.metrics import concordance_index_censored
from sksurv.util import Surv


def _survival_data(seed: int = 42) -> dict[str, Any]:
    """带真实信号的生存数据：风险 = 0.04*age + 0.8*treatment - 0.5*biomarker。"""
    rng = np.random.default_rng(seed)
    n = 160
    age = rng.normal(60, 10, n)
    treatment = rng.integers(0, 2, n).astype(float)
    biomarker = rng.normal(0, 1, n)
    X = pd.DataFrame(
        {
            "age": age,
            "treatment": treatment,
            "biomarker": biomarker,
            "noise": rng.normal(0, 1, n),  # 纯噪声对照：重要性应低于三个真实信号
        }
    )
    linear = 0.08 * age + 1.2 * treatment - 1.0 * biomarker
    scale = 20.0 / np.exp(linear - linear.mean())
    time = rng.exponential(scale) + 1.0
    censor = rng.exponential(80.0, n)
    observed = np.minimum(time, censor)
    event = time <= censor
    y = Surv.from_arrays(event, observed)
    return {"X": X, "y": y}


def _load_adapter(key: str) -> Any:
    registry = ModelRegistry()
    registry.load()
    adapter = registry.get(key)
    assert adapter is not None, f"{key} 未经 entry_points 注册"
    return adapter


class TestRegistration:
    @pytest.mark.parametrize("key", ["km", "coxph", "rsf", "gbs"])
    def test_registered_via_entry_points(self, key: str) -> None:
        adapter = _load_adapter(key)
        assert adapter.task_types == ["survival"]
        assert adapter.version

    def test_for_task_includes_all_four(self) -> None:
        registry = ModelRegistry()
        registry.load()
        keys = {a.key for a in registry.for_task("survival")}
        assert {"km", "coxph", "rsf", "gbs"} <= keys


class TestKmAdapter:
    def test_fit_evaluate_baseline(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("km")
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        # KM 无协变量：所有样本风险相同（全 tied）→ C-index ≈ 0.5 基线
        assert m["c_index"] == pytest.approx(0.5, abs=1e-6)
        assert "ibs" in m
        assert 0.0 <= m["ibs"] <= 1.0
        json.dumps(m)  # 指标结构可序列化（落库前提）

    def test_predict_artifacts_curve(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("km")
        adapter.fit(d["X"], d["y"], {})
        art = adapter.predict_artifacts(d["X"], d["y"])
        assert "km_curve" in art
        curve = art["km_curve"]
        assert len(curve["times"]) == len(curve["survival"])
        assert curve["survival"][0] <= 1.0
        surv_pairs = zip(curve["survival"], curve["survival"][1:], strict=False)
        assert all(b <= a for a, b in surv_pairs)  # 单调不增
        json.dumps(art)

    def test_explain_none(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("km")
        adapter.fit(d["X"], d["y"], {})
        assert adapter.explain(d["X"]) is None


class TestCoxphAdapter:
    def test_recovers_signal(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("coxph")
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        assert m["c_index"] > 0.75  # 合成信号应被恢复
        assert "ibs" in m
        json.dumps(m)

    def test_metrics_from_central_module(self) -> None:
        """adapter 不自算指标：C-index 与 sksurv 官方实现一致（±1e-6）。"""
        d = _survival_data()
        adapter = _load_adapter("coxph")
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        risk = adapter._model.predict_partial_hazard(d["X"]).to_numpy()
        expected = concordance_index_censored(d["y"]["event"], d["y"]["time"], risk)[0]
        assert m["c_index"] == pytest.approx(expected, abs=1e-6)

    def test_explain_coefficients(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("coxph")
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        assert exp is not None and exp["type"] == "coefficients"
        rows = {r["feature"]: r for r in exp["table"]}
        assert rows["treatment"]["hr"] > 1.0  # HR = exp(coef) 方向与数据生成一致
        assert rows["biomarker"]["hr"] < 1.0
        json.dumps(exp)


class TestRsfAdapter:
    def test_recovers_signal(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("rsf")
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        assert m["c_index"] > 0.7
        assert "ibs" in m
        json.dumps(m)

    def test_explain_importance(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("rsf")
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        assert exp is not None and exp["type"] == "feature_importance"
        assert set(exp["importances"]) == {"age", "treatment", "biomarker", "noise"}
        imp = exp["importances"]
        # 三个真实信号的重要性均高于纯噪声特征
        assert min(imp["age"], imp["treatment"], imp["biomarker"]) > imp["noise"]


class TestGbsAdapter:
    def test_recovers_signal(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("gbs")
        adapter.fit(d["X"], d["y"], {})
        m = adapter.evaluate(d["X"], d["y"])
        assert m["c_index"] > 0.7
        assert "ibs" in m
        json.dumps(m)

    def test_explain_importance(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("gbs")
        adapter.fit(d["X"], d["y"], {})
        exp = adapter.explain(d["X"])
        assert exp is not None and exp["type"] == "feature_importance"
        assert set(exp["importances"]) == {"age", "treatment", "biomarker", "noise"}


class TestKmByRiskArtifacts:
    """km_by_risk 产物：中位风险分层 KM 曲线（docs/09 §3，T6.2）。"""

    @pytest.mark.parametrize("key", ["coxph", "rsf", "gbs"])
    def test_km_by_risk_groups(self, key: str) -> None:
        d = _survival_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], {})
        art = adapter.predict_artifacts(d["X"], d["y"])
        km = art["km_by_risk"]
        names = {g["name"] for g in km["groups"]}
        assert names == {"低风险", "高风险"}
        for g in km["groups"]:
            assert len(g["times"]) == len(g["survival"]) >= 2
            assert all(0.0 <= s <= 1.0 for s in g["survival"])
        json.dumps(art)

    def test_coxph_hr_forest_artifact(self) -> None:
        d = _survival_data()
        adapter = _load_adapter("coxph")
        adapter.fit(d["X"], d["y"], {})
        art = adapter.predict_artifacts(d["X"], d["y"])
        rows = {r["feature"]: r for r in art["hr_forest"]}
        assert rows["treatment"]["hr"] > 1.0
        assert rows["treatment"]["ci_lower"] <= rows["treatment"]["hr"]
        assert rows["treatment"]["ci_upper"] >= rows["treatment"]["hr"]


class TestProtocolCompliance:
    @pytest.mark.parametrize("key", ["km", "coxph", "rsf", "gbs"])
    def test_fit_evaluate_roundtrip_with_param_override(self, key: str) -> None:
        d = _survival_data()
        adapter = _load_adapter(key)
        adapter.fit(d["X"], d["y"], dict(adapter.default_params))
        m = adapter.evaluate(d["X"], d["y"])
        assert isinstance(m["c_index"], float)
