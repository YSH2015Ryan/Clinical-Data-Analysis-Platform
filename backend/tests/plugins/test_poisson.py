"""Poisson and negative-binomial plugin acceptance tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from app.engines.model_registry import validate_adapter
from app.plugins.builtin.poisson_models import NegativeBinomialAdapter, PoissonAdapter

from tests.fixtures.poisson_data import make_count_data


@pytest.fixture()
def count_data() -> tuple[pd.DataFrame, pd.Series]:
    return make_count_data()


def test_poisson_basic_fit(count_data: tuple[pd.DataFrame, pd.Series]) -> None:
    X, y = count_data
    adapter = PoissonAdapter()
    result = adapter.fit(X, y)
    fit = adapter.get_model_fit(result)

    assert adapter.task_types == ["regression"]
    assert fit["aic"] == pytest.approx(result.aic)
    assert fit["bic"] == pytest.approx(result.bic)
    assert fit["deviance"] == pytest.approx(result.deviance)
    assert set(fit["rate_ratios"]) == {"const", "age", "treatment"}
    assert set(fit["confidence_intervals"]) == set(fit["rate_ratios"])
    assert all(np.isfinite(fit[key]) for key in ("aic", "bic", "deviance"))
    assert all(value > 0 for value in fit["rate_ratios"].values())
    for name, interval in fit["confidence_intervals"].items():
        assert len(interval) == 2
        assert 0 < interval[0] <= fit["rate_ratios"][name] <= interval[1]


def test_poisson_count_outcome(count_data: tuple[pd.DataFrame, pd.Series]) -> None:
    X, y = count_data
    adapter = PoissonAdapter()
    result = adapter.fit(X, y)
    prediction = adapter.predict(result, X)

    assert prediction.shape == (len(y),)
    assert np.isfinite(prediction).all()
    assert (prediction >= 0).all()
    assert np.array_equal(adapter.predict_values(X), prediction)
    metrics = adapter.get_metrics(y, prediction)
    assert metrics["score"] == metrics["rmse"]
    assert {"score", "rmse", "mae"} <= metrics.keys()


def test_negative_binomial_overdispersion() -> None:
    rng = np.random.default_rng(7)
    X = pd.DataFrame({"exposure": np.linspace(0, 1, 240)})
    mean = np.exp(1.2 + 0.9 * X["exposure"].to_numpy())
    y = pd.Series(rng.negative_binomial(2, 2 / (2 + mean)))

    fit = NegativeBinomialAdapter()
    result = fit.fit(X, y)
    assert np.isfinite(fit.get_model_fit(result)["deviance"])
    assert np.isfinite(fit.predict(result, X)).all()


def test_negbin_vs_poisson_comparison() -> None:
    rng = np.random.default_rng(11)
    X = pd.DataFrame({"x": rng.normal(size=300)})
    mean = np.exp(1.0 + 0.5 * X["x"].to_numpy())
    y = pd.Series(rng.negative_binomial(1, 1 / (1 + mean)))

    poisson = PoissonAdapter()
    negbin = NegativeBinomialAdapter()
    poisson_result = poisson.fit(X, y)
    negbin_result = negbin.fit(X, y)
    assert negbin.get_model_fit(negbin_result)["aic"] < poisson.get_model_fit(poisson_result)["aic"]


def test_categorical_predictors(count_data: tuple[pd.DataFrame, pd.Series]) -> None:
    X, y = count_data
    sites = np.resize(np.array(["east", "north", "west"]), len(X))
    X = X.assign(site=sites)
    adapter = PoissonAdapter()
    result = adapter.fit(X, y)
    prediction = adapter.predict(result, X)
    west = X["site"].eq("west")
    subset_prediction = adapter.predict(result, X.loc[west])

    assert prediction.shape == (len(y),)
    assert np.allclose(subset_prediction, prediction[west.to_numpy()])


def test_missing_values(count_data: tuple[pd.DataFrame, pd.Series]) -> None:
    X, y = count_data
    X.loc[0, "age"] = np.nan
    with pytest.raises(ValueError, match=r"缺失|missing"):
        PoissonAdapter().fit(X, y)


def test_zero_counts() -> None:
    X = pd.DataFrame({"x": np.arange(30, dtype=float)})
    y = pd.Series(np.zeros(len(X), dtype=int))
    adapter = PoissonAdapter()
    result = adapter.fit(X, y)
    prediction = adapter.predict(result, X)
    assert np.isfinite(prediction).all()
    assert (prediction >= 0).all()
    assert np.allclose(prediction, prediction[0])


def test_registry_protocol_and_artifacts(count_data: tuple[pd.DataFrame, pd.Series]) -> None:
    X, y = count_data
    adapter = PoissonAdapter()
    adapter.fit(X, y)

    assert validate_adapter(adapter) == []
    assert adapter.evaluate(X, y)["score"] >= 0
    assert adapter.explain(X)["type"] == "rate_ratios"
    artifacts = adapter.predict_artifacts(X, y)
    assert len(artifacts["prediction_scatter"]["y_pred"]) == len(y)


@pytest.mark.parametrize(
    ("y", "message"),
    [
        (pd.Series([0.0, 1.5, 2.0]), "integer"),
        (pd.Series([0, -1, 2]), "non-negative"),
    ],
)
def test_invalid_count_outcomes(y: pd.Series, message: str) -> None:
    X = pd.DataFrame({"x": [0.0, 1.0, 2.0]})
    with pytest.raises(ValueError, match=message):
        PoissonAdapter().fit(X, y)


@pytest.mark.parametrize("alpha", [0, -1.0, float("inf"), True])
def test_negative_binomial_rejects_invalid_alpha(alpha: object) -> None:
    X, y = make_count_data(n=30)
    with pytest.raises(ValueError, match="alpha"):
        NegativeBinomialAdapter().fit(X, y, {"alpha": alpha})
