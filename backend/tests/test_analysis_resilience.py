"""T6.5 训练性能与失败治理测试（路线图 T6.5；docs/08 §3）。

- 失败原因分类：裸异常 → timeout/memory/convergence/data/unknown + 用户可读建议；
- 软时间限制分档：重模型 > 默认档；dispatch 签名携带 soft_time_limit；
- 大样本采样保护：回归/生存插件 max_train_rows 确定性分层子采样；
- 全量 fit 跳过规则：无可解释性产物且有 OOF 时不再双训练。
"""

from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.engines.failure import classify_model_failure
from app.plugins.builtin.sampling import stratified_row_subsample
from app.workers.analysis_tasks import (
    _model_soft_time_limit,
    _sign_model_tasks,
    _wants_explain,
)


class _FakeSoftTimeLimitExceeded(Exception):
    pass


# 模拟 billiard 的类名（engines 不 import celery/billiard,按类名鸭子识别）
_FakeSoftTimeLimitExceeded.__name__ = "SoftTimeLimitExceeded"


class TestClassifyFailure:
    def test_timeout_by_class_name(self) -> None:
        result = classify_model_failure(_FakeSoftTimeLimitExceeded("SoftTimeLimitExceeded()"))
        assert result["category"] == "timeout"
        assert result["message"] and result["suggestion"]

    def test_timeout_by_text(self) -> None:
        result = classify_model_failure(RuntimeError("Time limit exceeded when fitting"))
        assert result["category"] == "timeout"

    def test_memory(self) -> None:
        result = classify_model_failure(MemoryError("Unable to allocate array"))
        assert result["category"] == "memory"
        assert "内存" in result["message"]

    def test_convergence(self) -> None:
        result = classify_model_failure(ValueError("Objective did not converge"))
        assert result["category"] == "convergence"

    def test_data(self) -> None:
        result = classify_model_failure(ValueError("Input contains NaN or infinity"))
        assert result["category"] == "data"
        assert result["suggestion"]

    def test_unknown(self) -> None:
        result = classify_model_failure(RuntimeError("something unexpected"))
        assert result["category"] == "unknown"
        # 所有分类都必须给出用户可读提示与建议(失败信息用户可直接理解)
        for key in ("message", "suggestion"):
            assert result[key]


class TestSoftTimeLimitTier:
    def test_heavy_model_gets_longer_limit(self) -> None:
        heavy = _model_soft_time_limit("rsf")
        light = _model_soft_time_limit("logreg")
        assert heavy > light > 0

    def test_unknown_model_uses_default(self) -> None:
        assert _model_soft_time_limit("no_such_model") == _model_soft_time_limit("logreg")

    def test_dispatch_signatures_carry_soft_limit(self) -> None:
        signatures = _sign_model_tasks("run-1", ["logreg", "rsf"])
        options = [sig.options.get("soft_time_limit") for sig in signatures]
        assert options[0] == _model_soft_time_limit("logreg")
        assert options[1] == _model_soft_time_limit("rsf")


class TestStratifiedRowSubsample:
    def test_below_cap_returns_unchanged(self) -> None:
        X = pd.DataFrame({"a": range(50)})
        y = np.arange(50, dtype=float)
        strata = np.zeros(50, dtype=int)
        X_out, y_out = stratified_row_subsample(X, y, strata, max_rows=100)
        assert len(X_out) == 50
        assert len(y_out) == 50

    def test_deterministic_and_aligned(self) -> None:
        rng = np.random.default_rng(0)
        n = 1000
        X = pd.DataFrame({"a": rng.normal(size=n)})
        y = rng.normal(size=n)
        strata = pd.qcut(pd.Series(y), q=10, labels=False, duplicates="drop").to_numpy()
        X1, y1 = stratified_row_subsample(X, y, strata, max_rows=100)
        X2, _y2 = stratified_row_subsample(X, y, strata, max_rows=100)
        assert len(X1) == 100
        assert X1.equals(X2)  # 确定性(seed=42)
        # X/y 行对齐:y 值应等于对应 X 行在原数据中的 y
        assert np.allclose(y1, y[X1.index.to_numpy()])

    def test_strata_ratio_roughly_preserved(self) -> None:
        n = 2000
        X = pd.DataFrame({"a": range(n)})
        y = np.arange(n, dtype=float)
        strata = np.array([0] * 1800 + [1] * 200)  # 10% 阳性
        _, y_out = stratified_row_subsample(X, y, strata, max_rows=200)
        # 分层采样:取到的行应同时包含两类,且少数类占比不至于塌缩为 0
        idx = y_out.astype(int)
        rate = (idx >= 1800).mean()
        assert 0.05 <= rate <= 0.2


class TestAdapterSampling:
    def test_rf_reg_max_train_rows(self) -> None:
        from app.plugins.builtin.regression import RfRegressorAdapter

        rng = np.random.default_rng(1)
        X = pd.DataFrame({"a": rng.normal(size=100), "b": rng.normal(size=100)})
        y = rng.normal(size=100)
        adapter = RfRegressorAdapter()
        adapter.fit(X, y, {"max_train_rows": 30, "n_estimators": 5})
        assert len(adapter._X) == 30

    def test_rsf_max_train_rows(self) -> None:
        from app.plugins.builtin.survival import RsfAdapter
        from sksurv.util import Surv

        rng = np.random.default_rng(1)
        X = pd.DataFrame({"a": rng.normal(size=100)})
        event = np.array([True, False] * 50)
        time = rng.uniform(1, 100, size=100)
        y = Surv.from_arrays(event, time)
        adapter = RsfAdapter()
        adapter.fit(X, y, {"max_train_rows": 40, "n_estimators": 5})
        assert len(adapter._X) == 40
        # 事件列与 X 行对齐
        assert len(adapter._train_event) == 40


class _Caps:
    def __init__(self, capabilities: dict[str, Any]) -> None:
        self.capabilities = capabilities


class TestFullFitSkip:
    def test_km_like_model_skips_full_fit(self) -> None:
        proto = _Caps({"feature_importance": False, "shap": False})
        assert _wants_explain(proto) is False

    def test_explainable_model_keeps_full_fit(self) -> None:
        proto = _Caps({"feature_importance": True, "shap": False})
        assert _wants_explain(proto) is True

    def test_missing_capabilities_defaults_to_full_fit(self) -> None:
        # 显式空 capabilities → 明确无可解释性产物 → 可跳过;
        # 未声明 capabilities 的第三方插件 → 保守保留全量 fit
        assert _wants_explain(_Caps({})) is False
        assert _wants_explain(object()) is True


@pytest.mark.parametrize("key", ["xgboost", "lightgbm"])
def test_classifier_n_jobs(key: str) -> None:
    from app.plugins.builtin import classification

    adapter_cls = {
        "xgboost": classification.XgboostAdapter,
        "lightgbm": classification.LightgbmAdapter,
    }[key]
    model = adapter_cls()._build({**adapter_cls.default_params})
    params = model.get_params()
    assert params.get("n_jobs") == -1


def test_lightgbm_complexity_cap_only_on_large_data() -> None:
    """min_child_samples=100 仅在大样本启用；小数据套用会严重欠拟合（AUC≈0.57 教训）。"""
    from app.plugins.builtin.classification import LightgbmAdapter

    rng = np.random.default_rng(0)
    X = pd.DataFrame({"a": rng.normal(size=200), "b": rng.normal(size=200)})
    y = np.array([0, 1] * 100)
    adapter = LightgbmAdapter()
    adapter.fit(X, y, {"n_estimators": 5})
    assert adapter._model.get_params().get("min_child_samples", 20) == 20

    X_big = pd.DataFrame({"a": rng.normal(size=10100), "b": rng.normal(size=10100)})
    y_big = np.array([0, 1] * 5050)
    adapter_big = LightgbmAdapter()
    adapter_big.fit(X_big, y_big, {"n_estimators": 1})
    assert adapter_big._model.get_params()["min_child_samples"] == 100
