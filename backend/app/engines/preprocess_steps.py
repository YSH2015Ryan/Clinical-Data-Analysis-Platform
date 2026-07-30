"""预处理步骤转换器：missing / outlier / encode / scale / feature_select / derive（docs/06 §3）。

协议：sklearn 兼容（fit(df, y=None) / transform(df)），可嵌入 sklearn.Pipeline；
fit 阶段把统计量写入 ``self.statistics_``（T3.4 Snapshot 序列化用），transform
一律使用训练折统计量，保证防泄漏（docs/06 §4）。

分层纪律：engines 只依赖数据处理库（pandas/numpy/sklearn/simpleeval），禁止 import
fastapi/celery/sqlalchemy。
"""

import ast
import operator
from typing import Any, Literal, cast

import numpy as np
import pandas as pd
import simpleeval
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_selection import f_classif, f_regression
from sklearn.impute import KNNImputer
from sklearn.linear_model import Lasso

ColumnSelector = Literal["continuous"] | list[str]


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _resolve_columns(df: pd.DataFrame, selector: ColumnSelector) -> list[str]:
    if selector == "continuous":
        return _numeric_columns(df)
    return [c for c in selector if c in df.columns]


# ---------- missing ----------


class MissingTransformer(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """缺失值处理：median/mean/mode/knn/constant + per_column 覆盖 + 高缺失列删除。

    - 数值列按策略插补；非数值列默认 mode（knn 对非数值列退化为 mode）。
    - 缺失率 > drop_threshold 的列在 fit 时记录并于 transform 删除。
    - 全缺失列（无法计算统计量）填 constant_value 并记入 statistics_["warnings"]。
    """

    def __init__(
        self,
        default: Literal["median", "mean", "mode", "knn", "constant"] = "median",
        per_column: dict[str, str] | None = None,
        drop_threshold: float = 0.5,
        constant_value: Any = 0,
    ) -> None:
        self.default = default
        self.per_column = per_column
        self.drop_threshold = drop_threshold
        self.constant_value = constant_value

    def _strategy_for(self, col: str, is_numeric: bool) -> str:
        overrides = self.per_column or {}
        strategy = overrides.get(col, self.default)
        if not is_numeric and strategy in ("median", "mean", "knn"):
            return "mode"
        return strategy

    def fit(self, df: pd.DataFrame, y: Any = None) -> "MissingTransformer":
        statistics: dict[str, Any] = {"fill_values": {}, "dropped_columns": [], "warnings": {}}
        n = max(len(df), 1)
        self._knn_columns: list[str] = []
        self._knn_imputer: KNNImputer | None = None

        for col in df.columns:
            s = df[col]
            ratio = float(s.isna().sum()) / n
            if ratio > self.drop_threshold:
                statistics["dropped_columns"].append(col)
                continue
            is_numeric = pd.api.types.is_numeric_dtype(s)
            strategy = self._strategy_for(col, is_numeric)
            if strategy == "knn":
                if is_numeric:
                    self._knn_columns.append(col)
                continue  # knn 在 fit 末尾统一处理
            if strategy == "constant":
                statistics["fill_values"][col] = self.constant_value
                continue
            non_null = s.dropna()
            if non_null.empty:
                statistics["fill_values"][col] = self.constant_value
                statistics["warnings"][col] = "全缺失列无法插补，已填 constant_value"
                continue
            if strategy == "median":
                statistics["fill_values"][col] = float(non_null.median())
            elif strategy == "mean":
                statistics["fill_values"][col] = float(non_null.mean())
            else:  # mode
                statistics["fill_values"][col] = non_null.mode().iloc[0]

        if self._knn_columns:
            self._knn_imputer = KNNImputer(n_neighbors=5)
            self._knn_imputer.fit(df[self._knn_columns])
            statistics["knn_columns"] = self._knn_columns

        self.statistics_ = statistics
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in self.statistics_["dropped_columns"]:
            if col in out.columns:
                out = out.drop(columns=[col])
        for col, value in self.statistics_["fill_values"].items():
            if col in out.columns:
                out[col] = out[col].fillna(value)
        if self._knn_imputer is not None:
            cols = [c for c in self._knn_columns if c in out.columns]
            if cols:
                out[cols] = self._knn_imputer.transform(out[cols])
        return out


# ---------- outlier ----------


class OutlierTransformer(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """异常值处理：iqr / zscore（clip 或 drop）；isolation_forest 预留。

    clip：按 fit 记录的上下界裁剪；drop：删除任一选中列越界的行。
    IQR=0 或 std=0 的列跳过（不裁剪，避免常量化）。
    """

    def __init__(
        self,
        method: Literal["iqr", "zscore", "isolation_forest"] = "iqr",
        action: Literal["clip", "drop"] = "clip",
        columns: ColumnSelector = "continuous",
        zscore_threshold: float = 3.0,
    ) -> None:
        self.method = method
        self.action = action
        self.columns = columns
        self.zscore_threshold = zscore_threshold

    def fit(self, df: pd.DataFrame, y: Any = None) -> "OutlierTransformer":
        if self.method == "isolation_forest":
            raise NotImplementedError("isolation_forest 异常检测将在后续里程碑提供")
        bounds: dict[str, dict[str, float]] = {}
        for col in _resolve_columns(df, self.columns):
            s = pd.to_numeric(df[col], errors="coerce")
            if self.method == "iqr":
                q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
                iqr = q3 - q1
                if iqr == 0.0:
                    if float(s.min()) == float(s.max()):
                        continue  # 常量列：不裁剪
                    # IQR 退化（高度重复值）：回退 1%/99% 分位界
                    lower, upper = float(s.quantile(0.01)), float(s.quantile(0.99))
                else:
                    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            else:  # zscore
                mean, std = float(s.mean()), float(s.std(ddof=0))
                if std == 0.0:
                    continue
                lower = mean - self.zscore_threshold * std
                upper = mean + self.zscore_threshold * std
            bounds[col] = {"lower": lower, "upper": upper}
        self.statistics_ = {"bounds": bounds, "method": self.method, "action": self.action}
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        bounds = cast(dict[str, dict[str, float]], self.statistics_["bounds"])
        if self.action == "clip":
            for col, b in bounds.items():
                if col in out.columns:
                    out[col] = pd.to_numeric(out[col], errors="coerce").clip(b["lower"], b["upper"])
            return out
        mask = pd.Series(True, index=out.index)
        for col, b in bounds.items():
            if col in out.columns:
                s = pd.to_numeric(out[col], errors="coerce")
                mask &= s.isna() | ((s >= b["lower"]) & (s <= b["upper"]))
        return out.loc[mask].reset_index(drop=True)


# ---------- encode ----------


class EncodeTransformer(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """类别编码：onehot / ordinal / auto（低基数 onehot，高基数序数）。

    - onehot：按训练折类别生成 ``{col}_{cat}`` 哑变量；未知类别 → 全零。
    - ordinal：显式 ordinal_columns 映射（顺序即编码）；未知类别 → -1。
    - auto：基数 ≤ onehot_max_cardinality → onehot，否则按排序类别序数化；未知 → -1。
    """

    def __init__(
        self,
        method: Literal["auto", "onehot", "ordinal", "target"] = "auto",
        onehot_max_cardinality: int = 10,
        ordinal_columns: dict[str, list[str]] | None = None,
    ) -> None:
        self.method = method
        self.onehot_max_cardinality = onehot_max_cardinality
        self.ordinal_columns = ordinal_columns

    def fit(self, df: pd.DataFrame, y: Any = None) -> "EncodeTransformer":
        if self.method == "target":
            raise NotImplementedError("target 编码需要结局列，将在任务编排层提供")
        explicit = self.ordinal_columns or {}
        plans: dict[str, dict[str, Any]] = {}
        for col in df.columns:
            s = df[col]
            if pd.api.types.is_numeric_dtype(s):
                continue
            if col in explicit:
                plans[col] = {"method": "ordinal", "categories": list(explicit[col])}
                continue
            if self.method == "ordinal":
                cats = sorted(str(v) for v in s.dropna().unique())
                plans[col] = {"method": "ordinal", "categories": cats}
                continue
            if self.method == "onehot":
                cats = sorted(str(v) for v in s.dropna().unique())
                plans[col] = {"method": "onehot", "categories": cats}
                continue
            # auto
            cardinality = int(s.nunique(dropna=True))
            cats = sorted(str(v) for v in s.dropna().unique())
            if cardinality <= self.onehot_max_cardinality:
                plans[col] = {"method": "onehot", "categories": cats}
            else:
                plans[col] = {"method": "ordinal", "categories": cats}
        self.statistics_ = {"columns": plans}
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        plans: dict[str, dict[str, Any]] = self.statistics_["columns"]
        for col, plan in plans.items():
            if col not in out.columns:
                continue
            s = out[col].astype("string")
            cats: list[str] = plan["categories"]
            if plan["method"] == "onehot":
                for cat in cats:
                    out[f"{col}_{cat}"] = (s == cat).fillna(False).astype(int)
                out = out.drop(columns=[col])
            else:  # ordinal
                mapping = {cat: i for i, cat in enumerate(cats)}
                out[col] = s.map(mapping).fillna(-1).astype(int)
        return out


# ---------- scale ----------


class ScaleTransformer(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """数值缩放：standard / minmax / robust；非数值列不动。

    方差或极差为 0 的列缩放为 0（不产生 NaN）。
    """

    def __init__(
        self,
        method: Literal["standard", "minmax", "robust"] = "standard",
        columns: ColumnSelector = "continuous",
    ) -> None:
        self.method = method
        self.columns = columns

    def fit(self, df: pd.DataFrame, y: Any = None) -> "ScaleTransformer":
        params: dict[str, dict[str, float]] = {}
        for col in _resolve_columns(df, self.columns):
            s = pd.to_numeric(df[col], errors="coerce")
            if self.method == "standard":
                params[col] = {"center": float(s.mean()), "scale": float(s.std(ddof=0))}
            elif self.method == "minmax":
                lo, hi = float(s.min()), float(s.max())
                params[col] = {"center": lo, "scale": hi - lo}
            else:  # robust
                q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
                params[col] = {"center": float(s.median()), "scale": q3 - q1}
        self.statistics_ = {"method": self.method, "params": params, "columns": list(params)}
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        params = cast(dict[str, dict[str, float]], self.statistics_["params"])
        for col, p in params.items():
            if col not in out.columns:
                continue
            s = pd.to_numeric(out[col], errors="coerce")
            scale = p["scale"]
            if scale == 0.0 or np.isnan(scale):
                out[col] = 0.0
            else:
                out[col] = (s - p["center"]) / scale
        return out


# ---------- feature_select ----------


class FeatureSelectTransformer(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """特征选择：variance_threshold / correlation / univariate / lasso（复用 sklearn）。

    只作用于数值列，非数值列原样保留。correlation 的 threshold=0 视为默认 0.95；
    univariate/lasso 需要 y（fit(df, y)），缺失抛 ValueError。
    """

    def __init__(
        self,
        method: Literal["variance_threshold", "correlation", "univariate", "lasso"] = (
            "variance_threshold"
        ),
        threshold: float = 0.0,
    ) -> None:
        self.method = method
        self.threshold = threshold

    def fit(self, df: pd.DataFrame, y: Any = None) -> "FeatureSelectTransformer":
        cols = _numeric_columns(df)
        dropped: list[str] = []
        scores: dict[str, float] = {}

        if self.method == "variance_threshold":
            variances = df[cols].var(ddof=0)
            scores = {c: float(variances[c]) for c in cols}
            dropped = [c for c in cols if float(variances[c]) <= self.threshold]
        elif self.method == "correlation":
            cutoff = self.threshold if self.threshold > 0 else 0.95
            corr = df[cols].corr().abs().to_numpy(dtype=float)
            for i, ci in enumerate(cols):
                if ci in dropped:
                    continue
                for j, cj in enumerate(cols[i + 1 :], start=i + 1):
                    if cj not in dropped and float(corr[i, j]) > cutoff:
                        dropped.append(cj)
        else:
            if y is None:
                raise ValueError(f"{self.method} 特征选择需要 y：fit(df, y)")
            y_arr = np.asarray(y)
            x = df[cols].to_numpy(dtype=float, copy=True)
            if self.method == "univariate":
                is_classification = len(np.unique(y_arr[~pd.isna(y_arr)])) <= 10
                f_values, _ = f_classif(x, y_arr) if is_classification else f_regression(x, y_arr)
                scores = {c: float(f_values[i]) for i, c in enumerate(cols)}
                dropped = [c for c in cols if scores[c] < self.threshold]
            else:  # lasso
                alpha = self.threshold if self.threshold > 0 else 0.01
                model = Lasso(alpha=alpha)
                model.fit(x, y_arr)
                coef = np.asarray(model.coef_, dtype=float)
                scores = {c: float(coef[i]) for i, c in enumerate(cols)}
                dropped = [c for c in cols if scores[c] == 0.0]

        self.statistics_ = {"method": self.method, "dropped": dropped, "scores": scores}
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        dropped = [c for c in self.statistics_["dropped"] if c in df.columns]
        return df.drop(columns=dropped)


# ---------- derive（simpleeval 白名单沙箱，禁止 eval 任意代码 —— docs/06 §3）----------

_DERIVE_FUNCTIONS: dict[str, Any] = {
    "log": np.log,
    "log2": np.log2,
    "log10": np.log10,
    "sqrt": np.sqrt,
    "exp": np.exp,
    "abs": np.abs,
    "floor": np.floor,
    "ceil": np.ceil,
    "round": np.round,
    "clip": np.clip,
    "minimum": np.minimum,
    "maximum": np.maximum,
}


def _string_guarded(guard: Any, plain: Any) -> Any:
    """simpleeval 的 safe_mult/safe_add 等对带 __len__ 对象做长度检查，

    会把 pandas Series 的比较结果求布尔值而报错；仅字符串操作数走原守卫，
    其余直接用普通运算符（Series 向量化运算无 DoS 面）。
    """

    def inner(a: Any, b: Any) -> Any:
        if isinstance(a, (str, bytes)) or isinstance(b, (str, bytes)):
            return guard(a, b)
        return plain(a, b)

    return inner


def _series_safe_power(a: Any, b: Any) -> Any:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return simpleeval.safe_power(a, b)  # 纯标量保留指数 DoS 守卫
    return a**b


_DERIVE_OPERATORS: dict[Any, Any] = {
    **simpleeval.DEFAULT_OPERATORS,
    ast.Mult: _string_guarded(simpleeval.safe_mult, operator.mul),
    ast.Add: _string_guarded(simpleeval.safe_add, operator.add),
    ast.LShift: _string_guarded(simpleeval.safe_lshift, operator.lshift),
    ast.RShift: _string_guarded(simpleeval.safe_rshift, operator.rshift),
    ast.Pow: _series_safe_power,
}


class DeriveTransformer(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """派生列：simpleeval 白名单求值（安全红线 CLAUDE.md §7）。

    可用变量 = 数据列名；可用函数 = _DERIVE_FUNCTIONS 白名单；
    属性访问 / 导入 / lambda / 内建函数一律拒绝（simpleeval 默认策略）。
    fit 时即对训练数据试算，非法表达式在 fit 阶段抛 ValueError。
    """

    def __init__(self, expressions: list[dict[str, str]]) -> None:
        self.expressions = expressions

    def _evaluate(self, df: pd.DataFrame, expr: str) -> Any:
        evaluator = simpleeval.SimpleEval(
            names={c: df[c] for c in df.columns},
            functions=_DERIVE_FUNCTIONS,
            operators=_DERIVE_OPERATORS,
        )
        try:
            return evaluator.eval(expr)
        except Exception as exc:  # simpleeval.InvalidExpression / SyntaxError / 数值错误
            raise ValueError(f"派生表达式 {expr!r} 非法或求值失败：{exc}") from exc

    def fit(self, df: pd.DataFrame, y: Any = None) -> "DeriveTransformer":
        for item in self.expressions:
            self._evaluate(df, item["expr"])  # 试算验证，失败即拒
        self.statistics_ = {
            "derived": [item["name"] for item in self.expressions],
            "expressions": list(self.expressions),
        }
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for item in self.expressions:
            out[item["name"]] = self._evaluate(out, item["expr"])
        return out
