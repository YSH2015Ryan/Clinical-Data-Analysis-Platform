"""Acceptance tests for the GEE model plugin."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.engines.model_registry import validate_adapter
from app.plugins.builtin.gee_models import GEEAdapter, detect_group_column


def _repeated_data() -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(42)
    subjects = np.repeat(np.arange(24), 4)
    x = rng.normal(size=len(subjects))
    probability = 1.0 / (1.0 + np.exp(-(0.7 * x + 0.25 * (subjects % 2))))
    y = pd.Series(rng.binomial(1, probability), name="outcome")
    return pd.DataFrame({"subject_id": subjects, "time": np.tile(np.arange(4), 24), "x": x}), y


def test_gee_basic_fit() -> None:
    X, y = _repeated_data()
    adapter = GEEAdapter()
    model = adapter.fit(X, y, {"task_type": "classification"})
    prediction = adapter.predict(model, X)
    assert adapter.used_gee
    assert prediction.shape == (len(y),)
    assert np.isfinite(prediction).all()
    assert np.logical_and(prediction >= 0, prediction <= 1).all()


def test_gee_no_groups_fallback_glm() -> None:
    rng = np.random.default_rng(3)
    X = pd.DataFrame({"x": np.linspace(-2, 2, 80)})
    y = pd.Series(1.0 + 0.8 * X["x"] + rng.normal(size=len(X)) * 0.1)
    adapter = GEEAdapter()
    model = adapter.fit(X, y, {"task_type": "regression"})
    assert not adapter.used_gee
    assert model.__class__.__name__.endswith("ResultsWrapper")
    assert adapter.get_model_fit(model)["used_gee"] is False


def test_gee_auto_detect_groups() -> None:
    X, _ = _repeated_data()
    assert detect_group_column(X) == "subject_id"
    adapter = GEEAdapter()
    adapter.fit(X, pd.Series(np.arange(len(X)) % 2), {"task_type": "classification"})
    assert adapter.group_column == "subject_id"


def test_gee_repeated_measures() -> None:
    X, y = _repeated_data()
    adapter = GEEAdapter()
    model = adapter.fit(X, y, {"task_type": "classification", "group_column": "subject_id"})
    assert model.nobs == len(y)
    assert adapter.predict(model, X.drop(columns="subject_id")).shape == (len(y),)


def test_gee_working_correlation() -> None:
    X, y = _repeated_data()
    adapter = GEEAdapter()
    adapter.fit(X, y, {"task_type": "classification", "working_correlation": "independence"})
    assert adapter.working_correlation == "independence"


def test_gee_model_fit_metrics() -> None:
    X, y = _repeated_data()
    adapter = GEEAdapter()
    model = adapter.fit(X, y, {"task_type": "classification"})
    fit = adapter.get_model_fit(model)
    assert "qic" in fit
    assert fit["qic"] is None or np.isfinite(fit["qic"])
    assert np.isfinite(fit["scale"])


def test_gee_coefficients_ci() -> None:
    X, y = _repeated_data()
    adapter = GEEAdapter()
    model = adapter.fit(X, y, {"task_type": "classification"})
    fit = adapter.get_model_fit(model)
    assert set(fit["odds_ratios"]) == {"const", "time", "x"}
    assert set(fit["confidence_intervals"]) == set(fit["odds_ratios"])
    assert all(len(interval) == 2 for interval in fit["confidence_intervals"].values())


def test_gee_registry_protocol() -> None:
    adapter = GEEAdapter()
    assert adapter.task_types == ["regression", "classification"]
    assert validate_adapter(adapter) == []
