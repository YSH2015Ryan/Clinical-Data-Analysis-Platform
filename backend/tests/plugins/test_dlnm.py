"""Acceptance tests for the simplified DLNM plugin."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app.engines.model_registry import ModelRegistry, validate_adapter
from app.plugins.builtin.dlnm_models import DLNMAdapter


def _data() -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(42)
    exposure = np.sin(np.linspace(0, 12, 120)) + rng.normal(0, 0.08, 120)
    second = rng.normal(size=120)
    lagged = np.r_[0.0, exposure[:-1]]
    y = 0.7 * exposure + 0.35 * lagged + 0.1 * second + rng.normal(0, 0.05, 120)
    return pd.DataFrame({"exposure": exposure, "temperature": second}), pd.Series(y)


def test_dlnm_basic_fit() -> None:
    X, y = _data()
    adapter = DLNMAdapter()
    model = adapter.fit(X, y, {"max_lag": 5, "lag_degree": 2})
    prediction = adapter.predict(model, X)
    assert prediction.shape == (len(y),)
    assert np.isfinite(prediction).all()


def test_dlnm_lag_structure() -> None:
    X, _ = _data()
    adapter = DLNMAdapter()
    matrix = adapter._create_lag_matrix(X[["exposure"]], max_lag=3)
    assert matrix.shape == (len(X), 4)
    np.testing.assert_allclose(matrix[3], X["exposure"].to_numpy()[[3, 2, 1, 0]])


def test_dlnm_lag_effects() -> None:
    X, y = _data()
    adapter = DLNMAdapter()
    adapter.fit(X, y, {"max_lag": 4, "lag_degree": 2})
    curves = adapter.get_lag_effects()
    assert set(curves) == set(X.columns)
    assert curves["exposure"]["lag"] == [0, 1, 2, 3, 4]
    assert len(curves["exposure"]["effect"]) == 5
    json.dumps(curves)


def test_dlnm_model_fit_metrics() -> None:
    X, y = _data()
    adapter = DLNMAdapter()
    model = adapter.fit(X, y)
    fit = adapter.get_model_fit(model)
    assert np.isfinite(fit["aic"])
    assert np.isfinite(fit["r2"])
    assert 0.0 <= fit["r2"] <= 1.0
    assert fit["max_lag"] == 7


def test_dlnm_time_series_support() -> None:
    X, y = _data()
    adapter = DLNMAdapter()
    adapter.fit(X, y, {"task_type": "time_series"})
    assert "time_series" in adapter.task_types
    assert "score" in adapter.evaluate(X, y)


def test_dlnm_registry_protocol() -> None:
    adapter = DLNMAdapter()
    assert validate_adapter(adapter) == []
    assert adapter.key == "dlnm"
    registry = ModelRegistry()
    registry.register(adapter, entry_point="tests:dlnm")
    assert [item.key for item in registry.for_task("time_series")] == ["dlnm"]
    X, y = _data()
    adapter.fit(X, y)
    artifacts = adapter.predict_artifacts(X, y)
    assert "lag_effect_curves" in artifacts
    json.dumps(artifacts)
