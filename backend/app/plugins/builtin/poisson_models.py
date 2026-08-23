"""Poisson and negative-binomial GLM model plugins.

The adapter keeps the design-matrix preparation deterministic so categorical
columns can be used in both fit and predict.  Estimation and confidence
intervals are delegated entirely to statsmodels.
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

import numpy as np
import pandas as pd
import statsmodels.api as sm

from app.engines.adapters import BaseModelAdapter


class PoissonAdapter(BaseModelAdapter):
    """Poisson regression with rate-ratio estimates."""

    key = "poisson"
    name = "Poisson Regression"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["regression"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": False,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {}

    def __init__(self) -> None:
        self._input_columns: list[Any] = []
        self._feature_columns: list[str] = []
        self._categorical_levels: dict[Any, list[Any]] = {}
        self._model: Any | None = None

    def _validate_inputs(
        self, X: pd.DataFrame, y: pd.Series
    ) -> tuple[pd.DataFrame, np.ndarray[Any, Any]]:
        frame = pd.DataFrame(X).copy()
        response = pd.Series(y).copy()
        if len(frame) != len(response):
            raise ValueError("X and y must contain the same number of rows")
        if len(frame) == 0:
            raise ValueError("X must contain at least one row")
        if frame.isna().any().any() or response.isna().any():
            raise ValueError("missing values are not supported")
        values = pd.to_numeric(response, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("y must contain finite numeric values")
        if (values < 0).any():
            raise ValueError("count outcomes must be non-negative")
        if not np.equal(values, np.floor(values)).all():
            raise ValueError("count outcomes must contain integer values")
        return frame, values

    def _encode(self, frame: pd.DataFrame, *, fit: bool) -> pd.DataFrame:
        """Encode categorical predictors without evaluating user expressions."""
        if fit:
            self._categorical_levels = {
                column: list(pd.Series(frame[column], dtype="category").cat.categories)
                for column in frame.columns
                if not pd.api.types.is_numeric_dtype(frame[column])
            }
        for column, levels in self._categorical_levels.items():
            if column not in frame:
                raise ValueError(f"predictors are missing fitted column {column!r}")
            unknown = set(pd.unique(frame[column])) - set(levels)
            if unknown:
                raise ValueError(
                    f"predictor {column!r} contains unknown categories: {sorted(map(str, unknown))}"
                )
            frame[column] = pd.Categorical(frame[column], categories=levels)
        encoded = pd.get_dummies(frame, drop_first=True, dtype=float)
        for column in encoded.columns:
            encoded[column] = pd.to_numeric(encoded[column], errors="raise")
        return encoded.astype(float)

    def _design_matrix(self, X: pd.DataFrame, *, fit: bool = False) -> pd.DataFrame:
        frame = pd.DataFrame(X).copy()
        if frame.isna().any().any():
            raise ValueError("missing values are not supported")
        if fit:
            self._input_columns = list(frame.columns)
        elif set(frame.columns) != set(self._input_columns):
            missing = set(self._input_columns) - set(frame.columns)
            extra = set(frame.columns) - set(self._input_columns)
            raise ValueError(
                f"predictor columns differ from fit; missing={sorted(map(str, missing))}, "
                f"extra={sorted(map(str, extra))}"
            )
        frame = frame.reindex(columns=self._input_columns)
        encoded = self._encode(frame, fit=fit)
        encoded.columns = [str(column) for column in encoded.columns]
        if fit:
            self._feature_columns = list(encoded.columns)
        else:
            encoded = encoded.reindex(columns=self._feature_columns, fill_value=0.0)
        encoded = encoded.astype(float)
        if not np.isfinite(encoded.to_numpy(dtype=float)).all():
            raise ValueError("predictors must contain finite numeric values")
        return cast(pd.DataFrame, sm.add_constant(encoded, has_constant="add"))

    def _family(self, params: dict[str, Any]) -> Any:
        del params
        return sm.families.Poisson()

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Fit a GLM and return the statsmodels result object.

        ``params`` is accepted for the existing CDAP registry protocol; model
        parameters are explicitly validated by subclasses before use.
        """
        options = {**self.default_params, **(params or {}), **kwargs}
        frame, values = self._validate_inputs(X, y)
        design = self._design_matrix(frame, fit=True)
        glm = sm.GLM(values, design, family=self._family(options))
        try:
            result = glm.fit()
        except ValueError:
            # A zero-only response has a boundary MLE and statsmodels' default
            # starting mean can produce a NaN deviance.  Retry through GLM's
            # own IRLS implementation with a finite, small starting mean.
            if not np.all(values == 0):
                raise
            start_params = np.zeros(design.shape[1], dtype=float)
            start_params[0] = -20.0
            result = glm.fit(start_params=start_params, maxiter=200)
        self._model = result
        return result

    def predict(self, model: Any, X: pd.DataFrame) -> np.ndarray[Any, Any]:
        """Predict expected counts from a fitted statsmodels result."""
        result = model if model is not None else self._model
        if result is None:
            raise ValueError("model has not been fitted")
        design = self._design_matrix(pd.DataFrame(X))
        return np.asarray(result.predict(design), dtype=float)

    def predict_values(self, X: Any) -> np.ndarray[Any, Any]:
        """Return predictions through the platform's regression plugin hook."""
        return self.predict(self._model, pd.DataFrame(X))

    def get_metrics(self, y_true: Any, y_pred: Any, **kwargs: Any) -> dict[str, Any]:
        """Return regression metrics with RMSE as the primary score."""
        del kwargs
        actual = np.asarray(y_true, dtype=float)
        predicted = np.asarray(y_pred, dtype=float)
        if actual.ndim != 1 or predicted.ndim != 1:
            raise ValueError("y_true and y_pred must be one-dimensional")
        if actual.shape != predicted.shape:
            raise ValueError("y_true and y_pred must have the same shape")
        rmse = float(sm.tools.eval_measures.rmse(actual, predicted))
        return {
            "score": rmse,
            "rmse": rmse,
            "mae": float(sm.tools.eval_measures.meanabs(actual, predicted)),
        }

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        """Registry-compatible evaluation wrapper."""
        return self.get_metrics(y_val, self.predict(self._model, pd.DataFrame(X_val)))

    def get_model_fit(self, model: Any) -> dict[str, Any]:
        """Return statsmodels fit statistics and exponentiated effects."""
        result = model if model is not None else self._model
        if result is None:
            raise ValueError("model has not been fitted")
        params = np.asarray(result.params, dtype=float)
        conf_int = np.asarray(result.conf_int(), dtype=float)
        names = [str(name) for name in result.params.index]
        rate_ratios = {
            name: float(np.exp(value)) for name, value in zip(names, params, strict=True)
        }
        confidence_intervals = {
            name: [float(np.exp(interval[0])), float(np.exp(interval[1]))]
            for name, interval in zip(names, conf_int, strict=True)
        }
        bic = getattr(result, "bic", None)
        if bic is None or not np.isfinite(float(bic)):
            bic = float(-2 * result.llf + (result.df_model + 1) * np.log(result.nobs))
        return {
            "aic": float(result.aic),
            "bic": float(bic),
            "deviance": float(result.deviance),
            "rate_ratios": rate_ratios,
            "confidence_intervals": confidence_intervals,
            # Short aliases keep the epidemiology-facing names explicit.
            "rr": rate_ratios,
            "ci": confidence_intervals,
            "ci_95": confidence_intervals,
        }

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        """Return coefficient/rate-ratio table for the registry protocol."""
        fit = self.get_model_fit(self._model)
        return {
            "type": "rate_ratios",
            "table": [
                {
                    "feature": name,
                    "rate_ratio": value,
                    "ci_lower": fit["confidence_intervals"][name][0],
                    "ci_upper": fit["confidence_intervals"][name][1],
                }
                for name, value in fit["rate_ratios"].items()
            ],
        }

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return self.predict_artifacts_from_predictions(self.predict_values(X_val), y_val)

    def predict_artifacts_from_predictions(self, predictions: Any, y_val: Any) -> dict[str, Any]:
        """Build scatter data from OOF predictions supplied by the worker."""
        return {
            "prediction_scatter": {
                "y_true": np.asarray(y_val, dtype=float).tolist(),
                "y_pred": np.asarray(predictions, dtype=float).tolist(),
            }
        }


class NegativeBinomialAdapter(PoissonAdapter):
    """Negative-binomial GLM for overdispersed count outcomes."""

    key = "negbin"
    name = "Negative Binomial Regression"
    default_params: ClassVar[dict[str, Any]] = {"alpha": 1.0}

    def _family(self, params: dict[str, Any]) -> Any:
        alpha = params.get("alpha", 1.0)
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not np.isfinite(alpha):
            raise ValueError("alpha must be a finite positive number")
        if alpha <= 0:
            raise ValueError("alpha must be greater than zero")
        return sm.families.NegativeBinomial(alpha=float(alpha))
