"""Acceptance tests for the GAM model plugin."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from app.engines.model_registry import validate_adapter
from app.plugins.builtin.gam_models import GAMAdapter


@pytest.fixture()
def regression_data() -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(42)
    x = np.linspace(-3.0, 3.0, 120)
    z = rng.normal(size=x.size)
    y = pd.Series(np.sin(x) + 0.25 * z, name="outcome")
    return pd.DataFrame({"x": x, "z": z}), y


@pytest.fixture()
def classification_data() -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(42)
    x = np.linspace(-3.0, 3.0, 140)
    z = rng.normal(size=x.size)
    probability = 1.0 / (1.0 + np.exp(-(1.3 * x - 0.35 * z)))
    y = pd.Series(rng.binomial(1, probability), name="outcome")
    return pd.DataFrame({"x": x, "z": z}), y


def test_gam_regression_basic(
    regression_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    X, y = regression_data
    adapter = GAMAdapter()
    model = adapter.fit(X, y)

    prediction = adapter.predict(model, X)
    assert adapter.task_types == ["regression", "classification"]
    assert prediction.shape == (len(y),)
    assert np.isfinite(prediction).all()


def test_gam_classification_basic(
    classification_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    X, y = classification_data
    adapter = GAMAdapter()
    model = adapter.fit(X, y)

    probability = adapter.predict(model, X)
    assert adapter._task_type == "classification"
    assert probability.shape == (len(y),)
    assert np.isfinite(probability).all()
    assert np.logical_and(probability >= 0.0, probability <= 1.0).all()


def test_gam_nonlinear_relationship(
    regression_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    X, y = regression_data
    adapter = GAMAdapter()
    adapter.fit(X, y, {"n_splines": 12})

    curve = adapter.partial_dependence(X)["x"]
    assert np.ptp(np.asarray(curve["values"], dtype=float)) > 0.5


def test_gam_categorical_predictors() -> None:
    rng = np.random.default_rng(7)
    groups = np.resize(np.array(["control", "treated", "follow-up"]), 120)
    X = pd.DataFrame({"group": pd.Series(groups, dtype="category")})
    y = pd.Series(rng.normal(size=120) + (groups == "treated") * 2.0)

    adapter = GAMAdapter()
    model = adapter.fit(X, y)
    prediction = adapter.predict(model, X)
    curve = adapter.partial_dependence(X)["group"]

    assert np.isfinite(prediction).all()
    assert curve["feature_type"] == "categorical"
    assert curve["grid"] == ["control", "treated", "follow-up"]


def test_gam_continuous_predictors(
    regression_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    X, y = regression_data
    adapter = GAMAdapter()
    adapter.fit(X[["x"]], y)
    curve = adapter.get_partial_dependence(X[["x"]], grid_points=25)["x"]

    assert curve["feature_type"] == "continuous"
    assert len(curve["grid"]) == 25
    assert len(curve["values"]) == 25


def test_gam_mixed_predictors() -> None:
    rng = np.random.default_rng(12)
    x = np.linspace(-2.0, 2.0, 100)
    group = np.resize(np.array(["a", "b"]), x.size)
    X = pd.DataFrame({"x": x, "group": group})
    y = pd.Series(np.cos(x) + (group == "b") * 0.75 + rng.normal(0, 0.05, x.size))

    adapter = GAMAdapter()
    model = adapter.fit(X, y)
    curves = adapter.partial_dependence(X)

    assert np.isfinite(adapter.predict(model, X)).all()
    assert curves["x"]["feature_type"] == "continuous"
    assert curves["group"]["feature_type"] == "categorical"


def test_gam_partial_dependence(
    regression_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    X, y = regression_data
    adapter = GAMAdapter()
    adapter.fit(X, y)
    explanation = adapter.explain(X)

    assert explanation is not None
    assert explanation["type"] == "partial_dependence"
    assert set(explanation["partial_dependence"]) == set(X.columns)
    json.dumps(explanation)


def test_gam_model_fit_metrics(
    regression_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    X, y = regression_data
    adapter = GAMAdapter()
    model = adapter.fit(X, y)
    fit = adapter.get_model_fit(model)

    assert np.isfinite(fit["aic"])
    assert np.isfinite(fit["deviance"])
    assert fit["n_splines"] == 10


def test_gam_missing_values(
    regression_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    X, y = regression_data
    X = X.copy()
    X.loc[0, "x"] = np.nan

    with pytest.raises(ValueError, match=r"missing|缺失"):
        GAMAdapter().fit(X, y)


def test_gam_collinear_features() -> None:
    x = np.linspace(-1.0, 1.0, 100)
    X = pd.DataFrame({"x1": x, "x2": x})
    y = pd.Series(x**2)

    adapter = GAMAdapter()
    model = adapter.fit(X, y)
    assert np.isfinite(adapter.predict(model, X)).all()


def test_gam_registry_protocol(
    regression_data: tuple[pd.DataFrame, pd.Series],
) -> None:
    X, y = regression_data
    adapter = GAMAdapter()
    adapter.fit(X, y)

    assert validate_adapter(adapter) == []
    assert "score" in adapter.evaluate(X, y)
    assert adapter.predict_artifacts(X, y)["prediction_scatter"]["y_pred"]
