"""Generalized estimating equation model plugin.

The adapter delegates estimation and working-correlation handling to
``statsmodels``.  It owns only platform-facing validation, deterministic
categorical encoding, automatic subject/group detection, and result
serialization.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, cast

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.genmod.cov_struct import (
    Autoregressive,
    Exchangeable,
    Independence,
    Nested,
    Unstructured,
)

from app.engines.adapters import BaseModelAdapter


logger = logging.getLogger(__name__)
_GROUP_KEYWORDS = ("id", "subject", "patient", "group")


def detect_group_column(X: pd.DataFrame) -> str | None:
    """Return a likely repeated-measures grouping column, if one exists.

    Name-based detection is preferred because it is explicit.  The fallback
    considers low-cardinality integer/string/categorical columns, which is
    useful for datasets whose subject identifier has a generic name.
    """

    frame = pd.DataFrame(X)
    if len(frame) == 0:
        return None
    for column in frame.columns:
        name = str(column).lower()
        if any(keyword in name for keyword in _GROUP_KEYWORDS):
            return str(column)
    for column in frame.columns:
        series = frame[column]
        if not (
            pd.api.types.is_integer_dtype(series)
            or pd.api.types.is_object_dtype(series)
            or isinstance(series.dtype, pd.CategoricalDtype)
            or pd.api.types.is_string_dtype(series)
        ):
            continue
        unique_ratio = float(series.nunique(dropna=True) / len(frame))
        if unique_ratio < 0.5:
            return str(column)
    return None


def _as_finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


class GEEAdapter(BaseModelAdapter):
    """GEE for longitudinal regression and binary classification."""

    key = "gee"
    name = "Generalized Estimating Equation"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["regression", "classification"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": False,
        "calibration": True,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "task_type": None,
        "group_column": None,
        "auto_detect_groups": True,
        "working_correlation": "exchangeable",
        "family": None,
    }

    def __init__(self) -> None:
        self._model: Any | None = None
        self._input_columns: list[Any] = []
        self._feature_columns: list[str] = []
        self._categorical_levels: dict[Any, list[Any]] = {}
        self._group_column: Any | None = None
        self._groups: np.ndarray[Any, Any] | None = None
        self._task_type: str | None = None
        self._classes: list[Any] = []
        self._family_name = "gaussian"
        self._working_correlation = "exchangeable"
        self._used_gee = False

    @property
    def group_column(self) -> Any | None:
        return self._group_column

    @property
    def used_gee(self) -> bool:
        return self._used_gee

    @property
    def working_correlation(self) -> str:
        return self._working_correlation

    @staticmethod
    def detect_group_column(X: pd.DataFrame) -> str | None:
        return detect_group_column(X)

    def _validate_frame(self, X: Any, *, fit: bool) -> pd.DataFrame:
        frame = X.copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        if frame.ndim != 2 or frame.shape[1] == 0:
            raise ValueError("X must contain at least one predictor column")
        if len(frame) == 0:
            raise ValueError("X must contain at least one row")
        if frame.columns.has_duplicates:
            raise ValueError("predictor columns must be unique")
        if frame.isna().any().any():
            raise ValueError("missing values are not supported")
        if fit:
            self._input_columns = list(frame.columns)
        else:
            expected = set(self._input_columns)
            actual = set(frame.columns)
            # A fitted grouping column is optional at prediction time.
            if self._group_column is not None:
                expected.discard(self._group_column)
                actual.discard(self._group_column)
            if not expected <= actual:
                missing = expected - actual
                raise ValueError(f"predictor columns differ from fit; missing={missing}")
            frame = frame.drop(columns=[self._group_column], errors="ignore")
            frame = frame.reindex(
                columns=[c for c in self._input_columns if c != self._group_column]
            )
        return frame

    def _encode(self, frame: pd.DataFrame, *, fit: bool) -> pd.DataFrame:
        frame = frame.copy()
        if fit:
            self._categorical_levels = {
                column: list(pd.Series(frame[column], dtype="category").cat.categories)
                for column in frame.columns
                if not pd.api.types.is_numeric_dtype(frame[column])
            }
        for column, levels in self._categorical_levels.items():
            unknown = set(pd.unique(frame[column])) - set(levels)
            if unknown:
                raise ValueError(f"predictor {column!r} contains unknown categories")
            frame[column] = pd.Categorical(frame[column], categories=levels)
        encoded = pd.get_dummies(frame, drop_first=True, dtype=float)
        encoded.columns = [str(column) for column in encoded.columns]
        if fit:
            self._feature_columns = list(encoded.columns)
        else:
            encoded = encoded.reindex(columns=self._feature_columns, fill_value=0.0)
        encoded = encoded.astype(float)
        if not np.isfinite(encoded.to_numpy()).all():
            raise ValueError("predictors must contain finite numeric values")
        return cast(pd.DataFrame, sm.add_constant(encoded, has_constant="add"))

    def _family(self, options: dict[str, Any], task_type: str) -> Any:
        requested = options.get("family")
        if requested is None:
            requested = "binomial" if task_type == "classification" else "gaussian"
        if not isinstance(requested, str):
            # Allow callers to pass a configured statsmodels family instance.
            if hasattr(requested, "link"):
                self._family_name = requested.__class__.__name__.lower()
                return requested
            raise ValueError("family must be a statsmodels family or a supported name")
        name = requested.lower().replace("-", "_")
        families = {
            "gaussian": sm.families.Gaussian,
            "normal": sm.families.Gaussian,
            "binomial": sm.families.Binomial,
            "poisson": sm.families.Poisson,
            "negative_binomial": sm.families.NegativeBinomial,
            "negbin": sm.families.NegativeBinomial,
        }
        if name not in families:
            raise ValueError(f"unsupported family {requested!r}")
        self._family_name = "binomial" if name == "binomial" else name
        return families[name]()

    @staticmethod
    def _cov_struct(value: Any) -> tuple[Any, str]:
        if value is None:
            value = "exchangeable"
        if not isinstance(value, str):
            return value, value.__class__.__name__.lower()
        name = value.lower().replace("-", "_")
        structures: dict[str, Any] = {
            "independence": Independence,
            "independent": Independence,
            "exchangeable": Exchangeable,
            "ar1": Autoregressive,
            "autoregressive": Autoregressive,
            "nested": Nested,
            "unstructured": Unstructured,
        }
        if name not in structures:
            raise ValueError(f"unsupported working_correlation {value!r}")
        return structures[name](), name

    def _resolve_task(
        self, y: pd.Series, options: dict[str, Any]
    ) -> tuple[str, np.ndarray[Any, Any]]:
        requested = options.get("task_type")
        values = pd.Series(y)
        if requested is None:
            requested = "classification" if values.nunique(dropna=True) == 2 else "regression"
        if requested not in {"classification", "regression"}:
            raise ValueError("task_type must be 'regression' or 'classification'")
        if requested == "classification":
            classes = list(pd.unique(values))
            if len(classes) != 2:
                raise ValueError("classification requires exactly two outcome classes")
            self._classes = classes
            mapping = {value: index for index, value in enumerate(classes)}
            encoded = np.asarray([mapping[value] for value in values], dtype=float)
            return requested, encoded
        numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(numeric).all():
            raise ValueError("regression outcome must contain finite numeric values")
        return requested, numeric

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        options = {**self.default_params, **(params or {}), **kwargs}
        frame = self._validate_frame(X, fit=True)
        response = pd.Series(y)
        if len(frame) != len(response):
            raise ValueError("X and y must contain the same number of rows")
        if response.isna().any():
            raise ValueError("missing values are not supported")
        self._task_type, values = self._resolve_task(response, options)

        explicit_group = options.get("group_column", options.get("group_col"))
        if explicit_group is not None:
            if explicit_group not in frame.columns:
                raise ValueError(f"group column {explicit_group!r} is not present in X")
            group_column = explicit_group
        elif options.get("auto_detect_groups", True):
            group_column = detect_group_column(frame)
        else:
            group_column = None
        supplied_groups = options.get("groups")
        if supplied_groups is not None:
            groups = pd.Series(supplied_groups)
            if len(groups) != len(frame):
                raise ValueError("groups must contain one value per row")
            groups = groups.to_numpy()
        elif group_column is not None:
            groups = frame[group_column].to_numpy()
        else:
            groups = None
        self._group_column = group_column
        self._groups = groups
        feature_frame = frame.drop(columns=[group_column], errors="ignore")
        design = self._encode(feature_frame, fit=True)
        family = self._family(options, self._task_type)
        self._working_correlation = str(options.get("working_correlation", "exchangeable"))
        if groups is None:
            logger.warning("No grouping variable detected; falling back to GLM")
            result = sm.GLM(values, design, family=family).fit()
            self._used_gee = False
        else:
            cov_struct, corr_name = self._cov_struct(options.get("working_correlation"))
            self._working_correlation = corr_name
            result = sm.GEE(
                values, design, groups=groups, family=family, cov_struct=cov_struct
            ).fit()
            self._used_gee = True
        self._model = result
        return result

    def predict(self, model: Any, X: pd.DataFrame) -> np.ndarray[Any, Any]:
        result = model if model is not None else self._model
        if result is None:
            raise ValueError("model has not been fitted")
        frame = self._validate_frame(X, fit=False)
        design = self._encode(frame, fit=False)
        return np.asarray(result.predict(design), dtype=float).reshape(-1)

    def predict_values(self, X: Any) -> np.ndarray[Any, Any]:
        return self.predict(self._model, pd.DataFrame(X))

    def get_metrics(self, y_true: Any, y_pred: Any, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        actual = pd.to_numeric(pd.Series(y_true), errors="coerce").to_numpy(dtype=float)
        predicted = np.asarray(y_pred, dtype=float).reshape(-1)
        if actual.shape != predicted.shape:
            raise ValueError("y_true and y_pred must have the same shape")
        if self._task_type == "classification":
            labels = (predicted >= 0.5).astype(int)
            encoded = self._encode_metric_y(y_true)
            accuracy = float(np.mean(labels == encoded))
            return {"score": accuracy, "accuracy": accuracy}
        residual = actual - predicted
        rmse = float(np.sqrt(np.mean(residual**2)))
        return {"score": rmse, "rmse": rmse, "mae": float(np.mean(np.abs(residual)))}

    def _encode_metric_y(self, y_true: Any) -> np.ndarray[Any, Any]:
        if not self._classes:
            return pd.to_numeric(pd.Series(y_true), errors="coerce").to_numpy(dtype=float)
        mapping = {value: index for index, value in enumerate(self._classes)}
        try:
            return np.asarray([mapping[value] for value in pd.Series(y_true)], dtype=float)
        except KeyError as exc:
            raise ValueError(f"unknown class {exc.args[0]!r}") from exc

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return self.get_metrics(y_val, self.predict_values(X_val))

    def get_model_fit(self, model: Any | None = None) -> dict[str, Any]:
        result = model if model is not None else self._model
        if result is None:
            raise ValueError("model has not been fitted")
        params = np.asarray(result.params, dtype=float)
        conf_int = np.asarray(result.conf_int(), dtype=float)
        names = [str(name) for name in result.params.index]
        effects = {name: float(np.exp(value)) for name, value in zip(names, params, strict=True)}
        intervals = {
            name: [float(np.exp(bound[0])), float(np.exp(bound[1]))]
            for name, bound in zip(names, conf_int, strict=True)
        }
        qic: float | None = None
        qic_value = getattr(result, "qic", None)
        try:
            qic_value = qic_value() if callable(qic_value) else qic_value
            if isinstance(qic_value, (tuple, list, np.ndarray)):
                qic_value = qic_value[0]
            qic = _as_finite_float(qic_value)
        except Exception:
            qic = None
        scale = _as_finite_float(getattr(result, "scale", None))
        effect_key = "odds_ratios" if self._family_name == "binomial" else "risk_ratios"
        return {
            "qic": qic,
            "scale": scale,
            "aic": _as_finite_float(getattr(result, "aic", None)),
            "deviance": _as_finite_float(getattr(result, "deviance", None)),
            effect_key: effects,
            "confidence_intervals": intervals,
            "ci_95": intervals,
            "or": effects if effect_key == "odds_ratios" else {},
            "rr": effects if effect_key == "risk_ratios" else {},
            "group_column": self._group_column,
            "used_gee": self._used_gee,
            "working_correlation": self._working_correlation,
            "task_type": self._task_type,
        }

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        fit = self.get_model_fit(self._model)
        key = "odds_ratios" if self._family_name == "binomial" else "risk_ratios"
        return {
            "type": key,
            "table": [
                {
                    "feature": name,
                    key[:-1]: value,
                    "ci_lower": fit["confidence_intervals"][name][0],
                    "ci_upper": fit["confidence_intervals"][name][1],
                }
                for name, value in fit[key].items()
            ],
        }

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return self.predict_artifacts_from_predictions(self.predict_values(X_val), y_val)

    def predict_artifacts_from_predictions(self, predictions: Any, y_val: Any) -> dict[str, Any]:
        return {
            "prediction_scatter": {
                "y_true": np.asarray(y_val).reshape(-1).tolist(),
                "y_pred": np.asarray(predictions, dtype=float).reshape(-1).tolist(),
            }
        }
