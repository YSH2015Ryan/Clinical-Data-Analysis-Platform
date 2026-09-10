"""Generalized additive model plugin backed by :mod:`pygam`.

The adapter owns only the platform-facing data preparation and result
serialization.  Spline estimation, factor terms, and inference are delegated
to pygam's ``GAM`` and ``LogisticGAM`` implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

import numpy as np
import pandas as pd
from pygam import GAM, LogisticGAM, f, s
from sklearn.metrics import (
    accuracy_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)

from app.engines.adapters import BaseModelAdapter


@dataclass
class _FeatureSpec:
    """Fitted encoding metadata for one predictor."""

    name: Any
    kind: str
    categories: list[Any]


def _as_json_value(value: Any) -> Any:
    """Convert numpy/pandas values to JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(key): _as_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_as_json_value(item) for item in value.tolist()]
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.total_seconds()
    return value


class GAMAdapter(BaseModelAdapter):
    """Adapter for regression and binary-classification GAMs.

    Predictor columns are inferred as categorical when they are pandas
    categorical/object/bool columns, or low-cardinality integer columns.  All
    other numeric columns receive a pygam spline term.  Missing values are
    rejected deliberately: the preprocessing pipeline is the single place
    where a configured missing-value policy is applied.
    """

    key = "gam"
    name = "Generalized Additive Model"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["regression", "classification"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": False,
        "calibration": True,
        "partial_dependence": True,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "n_splines": 10,
        "spline_order": 3,
        "lam": 0.6,
        "max_iter": 100,
        "tol": 1e-4,
        "grid_points": 50,
    }

    def __init__(self) -> None:
        self._model: Any | None = None
        self._input_columns: list[Any] = []
        self._feature_specs: list[_FeatureSpec] = []
        self._training_matrix: np.ndarray[Any, Any] | None = None
        self._training_frame: pd.DataFrame | None = None
        self._task_type: str | None = None
        self._fit_options: dict[str, Any] = dict(self.default_params)
        self._classes: list[Any] = []
        self._n_splines = int(self.default_params["n_splines"])
        self._grid_points = int(self.default_params["grid_points"])

    @property
    def model(self) -> Any | None:
        """Expose the fitted pygam object for callers that need it."""
        return self._model

    def _validate_frame(self, X: Any, *, fit: bool) -> pd.DataFrame:
        frame = X.copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        if frame.ndim != 2 or frame.shape[1] == 0:
            raise ValueError("X must contain at least one predictor column")
        if len(frame) == 0:
            raise ValueError("X must contain at least one row")
        if frame.columns.has_duplicates:
            raise ValueError("predictor columns must be unique")
        if frame.isna().any().any():
            raise ValueError("missing values are not supported; preprocess them before fitting")
        if fit:
            self._input_columns = list(frame.columns)
        else:
            expected = set(self._input_columns)
            actual = set(frame.columns)
            if actual != expected:
                missing = expected - actual
                extra = actual - expected
                raise ValueError(
                    f"predictor columns differ from fit; missing={sorted(map(str, missing))}, "
                    f"extra={sorted(map(str, extra))}"
                )
            frame = frame.reindex(columns=self._input_columns)
        return frame

    @staticmethod
    def _categorical_override(options: dict[str, Any]) -> set[Any]:
        columns = options.get("categorical_columns", options.get("categorical_features", []))
        if columns is None:
            return set()
        if isinstance(columns, dict):
            columns = [key for key, value in columns.items() if bool(value)]
        if isinstance(columns, (str, bytes)):
            columns = [columns]
        try:
            return set(columns)
        except TypeError as exc:
            raise ValueError("categorical_columns must be a sequence of column names") from exc

    def _detect_features(self, frame: pd.DataFrame, options: dict[str, Any]) -> list[_FeatureSpec]:
        overrides = self._categorical_override(options)
        unknown_overrides = overrides - set(frame.columns)
        if unknown_overrides:
            raise ValueError(f"categorical_columns contain unknown columns: {unknown_overrides}")
        feature_types = options.get("feature_types", {})
        if feature_types is None:
            feature_types = {}
        if not isinstance(feature_types, dict):
            raise ValueError(
                "feature_types must be a mapping of column name to continuous/categorical"
            )

        specs: list[_FeatureSpec] = []
        for column in frame.columns:
            series = frame[column]
            requested = feature_types.get(column)
            if requested is not None and requested not in {"continuous", "categorical"}:
                raise ValueError(f"feature_types[{column!r}] must be 'continuous' or 'categorical'")
            if requested is not None:
                kind = requested
            elif column in overrides or (
                isinstance(series.dtype, pd.CategoricalDtype)
                or pd.api.types.is_object_dtype(series)
                or pd.api.types.is_string_dtype(series)
                or pd.api.types.is_bool_dtype(series)
            ):
                kind = "categorical"
            elif pd.api.types.is_numeric_dtype(series):
                unique_count = int(series.nunique(dropna=True))
                # Integer-coded groups are common in clinical data.  A binary
                # numeric predictor is categorical regardless of its dtype.
                kind = (
                    "categorical"
                    if unique_count <= 2
                    or (
                        pd.api.types.is_integer_dtype(series)
                        and unique_count <= 10
                        and unique_count <= max(2, int(np.sqrt(len(series))))
                    )
                    else "continuous"
                )
            else:
                kind = "categorical"

            categories: list[Any] = []
            if kind == "categorical":
                categories = pd.unique(series).tolist()
                if not categories:
                    raise ValueError(f"categorical predictor {column!r} has no levels")
            specs.append(_FeatureSpec(name=column, kind=kind, categories=categories))
        return specs

    def _encode_frame(self, frame: pd.DataFrame, *, fit: bool) -> np.ndarray[Any, Any]:
        if fit:
            self._feature_specs = self._detect_features(frame, self._fit_options)
        if len(self._feature_specs) != len(self._input_columns):
            raise ValueError("model has no fitted predictor metadata")

        encoded = np.empty((len(frame), len(self._feature_specs)), dtype=float)
        for index, spec in enumerate(self._feature_specs):
            series = frame[spec.name]
            if spec.kind == "categorical":
                categories = spec.categories
                codes = pd.Categorical(series, categories=categories).codes
                if (codes < 0).any():
                    unknown = pd.unique(series[~series.isin(categories)]).tolist()
                    raise ValueError(
                        f"predictor {spec.name!r} contains unknown categories: "
                        f"{sorted(map(str, unknown))}"
                    )
                encoded[:, index] = np.asarray(codes, dtype=float)
            else:
                values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
                if not np.isfinite(values).all():
                    raise ValueError(f"predictor {spec.name!r} must contain finite numeric values")
                encoded[:, index] = values
        return encoded

    @staticmethod
    def _sorted_unique(values: pd.Series) -> list[Any]:
        unique = pd.unique(values).tolist()
        try:
            return cast(list[Any], sorted(unique))
        except TypeError:
            return unique

    def _prepare_response(
        self, y: Any, options: dict[str, Any]
    ) -> tuple[np.ndarray[Any, Any], str]:
        response = pd.Series(y)
        if len(response) == 0:
            raise ValueError("y must contain at least one row")
        if response.isna().any():
            raise ValueError("missing values are not supported in y")

        requested = options.get("task_type", options.get("task"))
        if requested is not None and requested not in {"regression", "classification"}:
            raise ValueError("task_type must be 'regression' or 'classification'")
        unique = self._sorted_unique(response)
        is_classification = requested == "classification" or (
            requested is None
            and (
                isinstance(response.dtype, pd.CategoricalDtype)
                or pd.api.types.is_object_dtype(response)
                or pd.api.types.is_string_dtype(response)
                or pd.api.types.is_bool_dtype(response)
                or len(unique) == 2
            )
        )
        if is_classification:
            if len(unique) != 2:
                raise ValueError("LogisticGAM currently supports exactly two outcome classes")
            self._classes = unique
            mapping = {value: index for index, value in enumerate(unique)}
            encoded = np.asarray([mapping[value] for value in response.tolist()], dtype=float)
            return encoded, "classification"

        values = pd.to_numeric(response, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("regression outcome must contain finite numeric values")
        self._classes = []
        return values, "regression"

    @staticmethod
    def _validate_integer_option(options: dict[str, Any], name: str, minimum: int) -> int:
        value = options[name]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(f"{name} must be an integer")
        if int(value) < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        return int(value)

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Fit and return a pygam ``GAM`` or ``LogisticGAM`` instance."""
        options = {**self.default_params, **(params or {}), **kwargs}
        self._fit_options = options
        frame = self._validate_frame(X, fit=True)
        matrix = self._encode_frame(frame, fit=True)
        if len(matrix) != len(y):
            raise ValueError("X and y must contain the same number of rows")
        values, task_type = self._prepare_response(y, options)

        self._n_splines = self._validate_integer_option(options, "n_splines", 4)
        spline_order = self._validate_integer_option(options, "spline_order", 1)
        if spline_order >= self._n_splines:
            raise ValueError("spline_order must be smaller than n_splines")
        max_iter = self._validate_integer_option(options, "max_iter", 1)
        tol = options["tol"]
        if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not np.isfinite(tol):
            raise ValueError("tol must be a finite non-negative number")
        if float(tol) < 0:
            raise ValueError("tol must be a finite non-negative number")
        lam = options["lam"]
        lam_values = np.asarray(lam, dtype=float)
        if not np.isfinite(lam_values).all() or (lam_values < 0).any():
            raise ValueError("lam must contain finite non-negative values")

        terms: Any | None = None
        for index, spec in enumerate(self._feature_specs):
            term = (
                s(index, n_splines=self._n_splines, spline_order=spline_order)
                if spec.kind == "continuous"
                else f(index)
            )
            terms = term if terms is None else terms + term

        model_cls: Any = LogisticGAM if task_type == "classification" else GAM
        model = model_cls(terms=terms, lam=lam, max_iter=max_iter, tol=float(tol), verbose=False)
        model.fit(matrix, values)

        self._model = model
        self._training_matrix = matrix
        self._training_frame = frame.copy()
        self._task_type = task_type
        self._grid_points = self._validate_integer_option(options, "grid_points", 2)
        return model

    def _require_model(self, model: Any | None = None) -> Any:
        result = model if model is not None else self._model
        if result is None or self._task_type is None:
            raise ValueError("model has not been fitted")
        return result

    def predict(self, model: Any, X: pd.DataFrame | None = None) -> np.ndarray[Any, Any]:
        """Return fitted values or positive-class probabilities."""
        if X is None:
            X = pd.DataFrame(model)
            model = None
        result = self._require_model(model)
        frame = self._validate_frame(X, fit=False)
        matrix = self._encode_frame(frame, fit=False)
        if self._task_type == "classification":
            prediction = result.predict_proba(matrix)
        else:
            prediction = result.predict(matrix)
        return cast(np.ndarray[Any, Any], np.asarray(prediction, dtype=float).reshape(-1))

    def predict_values(self, X: Any) -> np.ndarray[Any, Any]:
        """Registry-compatible prediction hook."""
        return self.predict(self._model, pd.DataFrame(X))

    def _encode_metric_y(self, y_true: Any) -> np.ndarray[Any, Any]:
        if self._task_type != "classification":
            actual = pd.to_numeric(pd.Series(y_true), errors="coerce").to_numpy(dtype=float)
            if not np.isfinite(actual).all():
                raise ValueError("y_true must contain finite numeric values")
            return actual
        if len(self._classes) != 2:
            raise ValueError("classification model has no fitted classes")
        values = pd.Series(y_true)
        mapping = {value: index for index, value in enumerate(self._classes)}
        try:
            encoded = np.asarray([mapping[value] for value in values.tolist()], dtype=float)
        except KeyError as exc:
            raise ValueError(f"y_true contains unknown class {exc.args[0]!r}") from exc
        return encoded

    def get_metrics(self, y_true: Any, y_pred: Any, **kwargs: Any) -> dict[str, Any]:
        """Return standard metrics with the platform's ``score`` alias."""
        del kwargs
        actual = self._encode_metric_y(y_true)
        predicted = np.asarray(y_pred, dtype=float).reshape(-1)
        if actual.shape != predicted.shape:
            raise ValueError("y_true and y_pred must have the same shape")
        if self._task_type == "classification":
            labels = (predicted >= 0.5).astype(int)
            metrics: dict[str, Any] = {
                "accuracy": float(accuracy_score(actual, labels)),
            }
            if len(np.unique(actual)) == 2:
                metrics["auc"] = float(roc_auc_score(actual, predicted))
                metrics["score"] = metrics["auc"]
            else:
                metrics["score"] = metrics["accuracy"]
            return metrics

        rmse = float(np.sqrt(mean_squared_error(actual, predicted)))
        return {
            "score": rmse,
            "rmse": rmse,
            "mae": float(mean_absolute_error(actual, predicted)),
            "r2": float(r2_score(actual, predicted)),
        }

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return self.get_metrics(y_val, self.predict_values(X_val))

    def get_model_fit(self, model: Any | None = None) -> dict[str, Any]:
        """Return pygam AIC, deviance, and configured spline count."""
        result = self._require_model(model)
        statistics = getattr(result, "statistics_", {})
        aic = float(statistics.get("AIC", np.nan))
        deviance = float(statistics.get("deviance", np.nan))
        if not np.isfinite(aic):
            raise ValueError("fitted GAM did not provide a finite AIC")
        if not np.isfinite(deviance):
            raise ValueError("fitted GAM did not provide a finite deviance")
        return {
            "aic": aic,
            "deviance": deviance,
            "n_splines": self._n_splines,
            "n_splines_by_feature": [
                self._n_splines if spec.kind == "continuous" else len(spec.categories)
                for spec in self._feature_specs
            ],
            "task_type": self._task_type,
        }

    def _partial_dependence_curve(
        self, result: Any, index: int, spec: _FeatureSpec, frame: pd.DataFrame, grid_points: int
    ) -> dict[str, Any]:
        base = np.asarray(self._encode_frame(frame.iloc[:1], fit=False)[0], dtype=float)
        if spec.kind == "categorical":
            display_grid = list(spec.categories)
            encoded_grid = np.tile(base, (len(display_grid), 1))
            encoded_grid[:, index] = np.arange(len(display_grid), dtype=float)
        else:
            values = pd.to_numeric(frame[spec.name], errors="coerce").to_numpy(dtype=float)
            low, high = float(np.min(values)), float(np.max(values))
            display_grid = np.linspace(low, high, grid_points).tolist()
            encoded_grid = np.tile(base, (grid_points, 1))
            encoded_grid[:, index] = np.asarray(display_grid, dtype=float)

        curve = result.partial_dependence(term=index, X=encoded_grid)
        # pygam returns ``(estimate, confidence_interval)`` when confidence
        # bands are enabled; versions differ on tuple versus list here.  Keep
        # the estimate only, while leaving a plain curve array untouched.
        if isinstance(curve, (tuple, list)) and len(curve) == 2:
            estimate = np.asarray(curve[0])
            if estimate.size == len(display_grid):
                curve = curve[0]
        return {
            "feature": str(spec.name),
            "feature_type": spec.kind,
            "grid": _as_json_value(display_grid),
            "values": _as_json_value(np.asarray(curve, dtype=float).reshape(-1)),
        }

    def get_partial_dependence(
        self, X: Any | None = None, *, grid_points: int | None = None
    ) -> dict[str, dict[str, Any]]:
        """Return one JSON-serializable partial-dependence curve per predictor."""
        result = self._require_model()
        frame = self._training_frame if X is None else self._validate_frame(X, fit=False)
        if frame is None:
            raise ValueError("model has not been fitted")
        points = self._grid_points if grid_points is None else grid_points
        if isinstance(points, bool) or not isinstance(points, (int, np.integer)) or points < 2:
            raise ValueError("grid_points must be an integer of at least 2")
        curves: dict[str, dict[str, Any]] = {}
        for index, spec in enumerate(self._feature_specs):
            curve = self._partial_dependence_curve(result, index, spec, frame, int(points))
            curves[str(spec.name)] = curve
        return curves

    def partial_dependence(
        self, X: Any | None = None, *, grid_points: int | None = None
    ) -> dict[str, dict[str, Any]]:
        """Alias for :meth:`get_partial_dependence`."""
        return self.get_partial_dependence(X, grid_points=grid_points)

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        curves = self.get_partial_dependence(X_val)
        return {"type": "partial_dependence", "partial_dependence": curves, "curves": curves}

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return self.predict_artifacts_from_predictions(self.predict_values(X_val), y_val)

    def predict_artifacts_from_predictions(self, predictions: Any, y_val: Any) -> dict[str, Any]:
        return {
            "prediction_scatter": {
                "y_true": _as_json_value(np.asarray(y_val).reshape(-1)),
                "y_pred": _as_json_value(np.asarray(predictions, dtype=float).reshape(-1)),
            }
        }
