"""Simplified distributed-lag non-linear model (DLNM) plugin.

This implementation intentionally keeps the exposure-response relationship
linear while representing the lag dimension with a polynomial basis.  It is a
small, dependency-light approximation suitable for time-series demonstrations;
it is not a replacement for the R ``dlnm`` package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
import pandas as pd
from scipy import linalg

from app.engines.adapters import BaseModelAdapter


@dataclass
class _DLNMModel:
    intercept: float
    coefficients: np.ndarray[Any, Any]
    columns: list[str]
    max_lag: int
    lag_degree: int
    rss: float
    tss: float
    nobs: int


def _json_value(value: Any) -> Any:
    """Convert numpy values and non-finite floats to JSON-safe values."""
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    return value


class DLNMAdapter(BaseModelAdapter):
    """Linear exposure response with a polynomial distributed-lag basis."""

    key = "dlnm"
    name = "Distributed Lag Non-linear Model (simplified)"
    version = "0.5.0"
    task_types: ClassVar[list[str]] = ["time_series", "regression"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": False,
        "lag_effects": True,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "max_lag": 7,
        "lag_degree": 2,
        "grid_points": 8,
    }

    def __init__(self) -> None:
        self._model: _DLNMModel | None = None
        self._input_columns: list[str] = []
        self._max_lag = int(self.default_params["max_lag"])
        self._lag_degree = int(self.default_params["lag_degree"])
        self._lag_basis = self._polynomial_lag_weights(self._max_lag, self._lag_degree)

    @staticmethod
    def _validate_option(value: Any, name: str, minimum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(f"{name} must be an integer")
        if int(value) < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        return int(value)

    @staticmethod
    def _frame(X: Any) -> pd.DataFrame:
        frame = X.copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        if frame.ndim != 2 or frame.shape[1] == 0:
            raise ValueError("X must contain at least one predictor column")
        if len(frame) == 0:
            raise ValueError("X must contain at least one row")
        if frame.columns.has_duplicates:
            raise ValueError("predictor columns must be unique")
        numeric = frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(numeric).all():
            raise ValueError("predictors must contain finite numeric values")
        frame = pd.DataFrame(numeric, columns=[str(column) for column in frame.columns])
        return frame

    @staticmethod
    def _response(y: Any, expected: int) -> np.ndarray[Any, Any]:
        values = pd.to_numeric(pd.Series(y), errors="coerce").to_numpy(dtype=float)
        if len(values) != expected:
            raise ValueError("X and y must contain the same number of rows")
        if len(values) == 0 or not np.isfinite(values).all():
            raise ValueError("y must contain finite numeric values")
        return values

    @staticmethod
    def _polynomial_lag_weights(max_lag: int, degree: int) -> np.ndarray[Any, Any]:
        """Return normalized polynomial basis rows for lags 0 through ``max_lag``."""
        max_lag = DLNMAdapter._validate_option(max_lag, "max_lag", 0)
        degree = DLNMAdapter._validate_option(degree, "lag_degree", 0)
        scaled = np.arange(max_lag + 1, dtype=float)
        if max_lag:
            scaled /= float(max_lag)
        return np.column_stack([scaled**power for power in range(degree + 1)])

    def _create_lag_matrix(self, X: Any, max_lag: int | None = None) -> np.ndarray[Any, Any]:
        """Create one lag matrix per input feature, concatenated by feature."""
        frame = self._frame(X)
        lag = self._max_lag if max_lag is None else self._validate_option(max_lag, "max_lag", 0)
        values = frame.to_numpy(dtype=float)
        matrices = []
        for column in range(values.shape[1]):
            matrix = np.zeros((len(frame), lag + 1), dtype=float)
            for offset in range(lag + 1):
                if offset == 0:
                    matrix[:, offset] = values[:, column]
                else:
                    matrix[offset:, offset] = values[:-offset, column]
            matrices.append(matrix)
        return np.concatenate(matrices, axis=1)

    def _design(self, X: Any) -> np.ndarray[Any, Any]:
        lag_matrix = self._create_lag_matrix(X, self._max_lag)
        n_features = len(self._input_columns)
        blocks = []
        for feature in range(n_features):
            start = feature * (self._max_lag + 1)
            stop = (feature + 1) * (self._max_lag + 1)
            feature_lags = lag_matrix[:, start:stop]
            blocks.extend(
                feature_lags @ self._lag_basis[:, power : power + 1]
                for power in range(self._lag_degree + 1)
            )
        return np.column_stack([np.ones(len(lag_matrix)), *blocks])

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> _DLNMModel:
        options = {**self.default_params, **(params or {}), **kwargs}
        requested_task = options.get("task_type", options.get("task"))
        if requested_task is not None and requested_task not in self.task_types:
            raise ValueError("task_type must be 'time_series' or 'regression'")
        frame = self._frame(X)
        values = self._response(y, len(frame))
        self._input_columns = list(frame.columns)
        self._max_lag = self._validate_option(options["max_lag"], "max_lag", 0)
        self._lag_degree = self._validate_option(options["lag_degree"], "lag_degree", 0)
        self._lag_basis = self._polynomial_lag_weights(self._max_lag, self._lag_degree)
        design = self._design(frame)
        coefficients, _, _, _ = linalg.lstsq(design, values)
        fitted = design @ coefficients
        residual = values - fitted
        model = _DLNMModel(
            intercept=float(coefficients[0]),
            coefficients=np.asarray(coefficients[1:], dtype=float).reshape(
                len(self._input_columns), self._lag_degree + 1
            ),
            columns=list(self._input_columns),
            max_lag=self._max_lag,
            lag_degree=self._lag_degree,
            rss=float(np.dot(residual, residual)),
            tss=float(
                np.dot(
                    values - float(np.mean(values)),
                    values - float(np.mean(values)),
                )
            ),
            nobs=len(values),
        )
        self._model = model
        return model

    def _require_model(self, model: Any | None = None) -> _DLNMModel:
        result = model if model is not None else self._model
        if not isinstance(result, _DLNMModel):
            raise ValueError("model has not been fitted")
        return result

    def predict(self, model: Any, X: pd.DataFrame) -> np.ndarray[Any, Any]:
        result = self._require_model(model)
        frame = self._frame(X)
        if list(frame.columns) != result.columns:
            raise ValueError("predictor columns differ from fit")
        design = self._design(frame)
        coefficients = result.coefficients.reshape(-1)
        return np.asarray(result.intercept + design[:, 1:] @ coefficients, dtype=float)

    def predict_values(self, X: Any) -> np.ndarray[Any, Any]:
        return self.predict(self._model, pd.DataFrame(X))

    def get_metrics(self, y_true: Any, y_pred: Any, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        actual = pd.to_numeric(pd.Series(y_true), errors="coerce").to_numpy(dtype=float)
        predicted = np.asarray(y_pred, dtype=float).reshape(-1)
        if actual.shape != predicted.shape or not np.isfinite(actual).all():
            raise ValueError("y_true and y_pred must have the same finite shape")
        residual = actual - predicted
        rss = float(np.dot(residual, residual))
        centered = actual - float(np.mean(actual))
        tss = float(np.dot(centered, centered))
        r2 = 1.0 - rss / tss if tss > 0 else 0.0
        rmse = float(np.sqrt(np.mean(residual**2)))
        return {
            "score": r2,
            "r2": r2,
            "r_squared": r2,
            "rmse": rmse,
            "mae": float(np.mean(np.abs(residual))),
        }

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return self.get_metrics(y_val, self.predict_values(X_val))

    def get_lag_effects(self, model: Any | None = None) -> dict[str, dict[str, Any]]:
        result = self._require_model(model)
        lags = np.arange(result.max_lag + 1, dtype=float)
        scaled = lags / result.max_lag if result.max_lag else lags
        curves: dict[str, dict[str, Any]] = {}
        for index, column in enumerate(result.columns):
            beta = result.coefficients[index]
            effects = np.polynomial.polynomial.polyval(scaled, beta)
            curves[column] = {
                "lag": lags.astype(int).tolist(),
                "effect": _json_value(effects),
                "exposure_response": "linear",
            }
        return curves

    lag_effect_curves = get_lag_effects
    get_lag_effect_curves = get_lag_effects

    def get_model_fit(self, model: Any | None = None) -> dict[str, Any]:
        result = self._require_model(model)
        k = len(result.coefficients.reshape(-1)) + 1
        variance = max(result.rss / result.nobs, np.finfo(float).tiny)
        aic = float(result.nobs * np.log(2.0 * np.pi * variance) + result.nobs + 2.0 * k)
        effects = self.get_lag_effects(result)
        r2 = 1.0 - result.rss / result.tss if result.tss > 0 else 0.0
        return {
            "aic": aic,
            "r2": float(r2),
            "r_squared": float(r2),
            "lag_effects": effects,
            "lag_effect_curves": effects,
            "lag_weights": _json_value(
                self._polynomial_lag_weights(result.max_lag, result.lag_degree)
            ),
            "max_lag": result.max_lag,
            "lag_degree": result.lag_degree,
            "nobs": result.nobs,
            "rss": result.rss,
        }

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        del X_val
        curves = self.get_lag_effects()
        return {"type": "lag_effects", "lag_effects": curves, "curves": curves}

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return self.predict_artifacts_from_predictions(self.predict_values(X_val), y_val)

    def predict_artifacts_from_predictions(self, predictions: Any, y_val: Any) -> dict[str, Any]:
        return {
            "prediction_scatter": {
                "y_true": _json_value(np.asarray(y_val).reshape(-1)),
                "y_pred": _json_value(np.asarray(predictions, dtype=float).reshape(-1)),
            },
            "lag_effect_curves": self.get_lag_effects(),
        }
