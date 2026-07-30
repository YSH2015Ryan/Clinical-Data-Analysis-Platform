"""T3.2 预处理步骤单测：missing/outlier/encode/scale（docs/06 §3）。

边界覆盖（docs/06 §6 DoD）：全缺失列、单值列、未知类别出现在验证集。
协议：fit(df, y=None) / transform(df)，sklearn Pipeline 兼容。
"""

import numpy as np
import pandas as pd
import pytest
from app.engines.preprocess_steps import (
    EncodeTransformer,
    MissingTransformer,
    OutlierTransformer,
    ScaleTransformer,
)
from sklearn.pipeline import Pipeline


@pytest.fixture()
def train_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [20.0, 30.0, np.nan, 50.0, 60.0, 70.0],
            "wbc": [5.0, 6.0, 7.0, np.nan, 9.0, 10.0],
            "gender": ["男", "女", None, "男", "女", "男"],
            "stage": ["I", "II", "I", "III", "II", "I"],
            "const": [1.0] * 6,
            "all_nan": [np.nan] * 6,
        }
    )


class TestMissing:
    def test_median_and_mode(self, train_df: pd.DataFrame) -> None:
        t = MissingTransformer(default="median")
        t.fit(train_df)
        out = t.transform(train_df)
        assert out["age"].isna().sum() == 0
        assert out["age"].iloc[2] == pytest.approx(50.0)  # median of [20,30,50,60,70]
        assert out["gender"].isna().sum() == 0
        assert out["gender"].iloc[2] == "男"  # mode

    def test_per_column_override(self, train_df: pd.DataFrame) -> None:
        t = MissingTransformer(default="median", per_column={"wbc": "mean"})
        t.fit(train_df)
        out = t.transform(train_df)
        assert out["wbc"].iloc[3] == pytest.approx(7.4)  # mean of [5,6,7,9,10]

    def test_drop_threshold(self, train_df: pd.DataFrame) -> None:
        t = MissingTransformer(default="median", drop_threshold=0.5)
        t.fit(train_df)
        out = t.transform(train_df)
        assert "all_nan" not in out.columns  # 100% 缺失 → 删除
        assert "age" in out.columns  # 1/6 < 0.5 → 保留

    def test_all_missing_column_kept_when_threshold_1(self, train_df: pd.DataFrame) -> None:
        t = MissingTransformer(default="median", drop_threshold=1.0)
        t.fit(train_df)
        out = t.transform(train_df)
        assert "all_nan" in out.columns  # 保留但无法插补 → 填 0 并记录警告
        assert out["all_nan"].isna().sum() == 0
        assert "all_nan" in t.statistics_["warnings"]

    def test_single_value_column(self, train_df: pd.DataFrame) -> None:
        t = MissingTransformer(default="median")
        t.fit(train_df)
        out = t.transform(train_df)
        assert out["const"].tolist() == [1.0] * 6

    def test_transform_uses_train_stats(self, train_df: pd.DataFrame) -> None:
        t = MissingTransformer(default="median")
        t.fit(train_df)
        val = pd.DataFrame(
            {
                "age": [np.nan],
                "wbc": [np.nan],
                "gender": [None],
                "stage": ["I"],
                "const": [1.0],
                "all_nan": [np.nan],
            }
        )
        out = t.transform(val)
        assert out["age"].iloc[0] == pytest.approx(50.0)  # 训练折中位数，非验证折


class TestOutlier:
    def test_iqr_clip(self) -> None:
        df = pd.DataFrame({"x": [1.0] * 20 + [2.0, 3.0, 100.0]})
        t = OutlierTransformer(method="iqr", action="clip")
        t.fit(df)
        out = t.transform(df)
        assert out["x"].max() < 100.0
        assert t.statistics_["bounds"]["x"]["upper"] > 3.0

    def test_zscore_clip(self) -> None:
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"x": np.append(rng.normal(0, 1, 100), [50.0])})
        t = OutlierTransformer(method="zscore", action="clip", zscore_threshold=3.0)
        t.fit(df)
        out = t.transform(df)
        assert out["x"].max() < 50.0

    def test_drop_action(self) -> None:
        df = pd.DataFrame({"x": [1.0] * 20 + [2.0, 3.0, 100.0]})
        t = OutlierTransformer(method="iqr", action="drop")
        t.fit(df)
        out = t.transform(df)
        assert len(out) == 22
        assert 100.0 not in out["x"].tolist()

    def test_columns_selector_list(self) -> None:
        df = pd.DataFrame({"a": [1.0] * 10 + [100.0], "b": [1.0] * 10 + [100.0]})
        t = OutlierTransformer(method="iqr", action="clip", columns=["a"])
        t.fit(df)
        out = t.transform(df)
        assert out["a"].max() < 100.0
        assert out["b"].max() == 100.0  # 未选列不动

    def test_iqr_zero_skips(self) -> None:
        df = pd.DataFrame({"x": [1.0] * 10})
        t = OutlierTransformer(method="iqr", action="clip")
        t.fit(df)
        out = t.transform(df)
        assert out["x"].tolist() == [1.0] * 10  # IQR=0 不裁剪


class TestEncode:
    def test_onehot(self) -> None:
        df = pd.DataFrame({"gender": ["男", "女", "男"], "x": [1.0, 2.0, 3.0]})
        t = EncodeTransformer(method="onehot")
        t.fit(df)
        out = t.transform(df)
        assert "gender" not in out.columns
        assert set(out.columns) == {"x", "gender_女", "gender_男"}
        assert out["x"].tolist() == [1.0, 2.0, 3.0]

    def test_unknown_category_all_zero(self) -> None:
        train = pd.DataFrame({"gender": ["男", "女"]})
        val = pd.DataFrame({"gender": ["未知"]})
        t = EncodeTransformer(method="onehot")
        t.fit(train)
        out = t.transform(val)
        assert out.iloc[0].tolist() == [0, 0]  # 未知类别 → 全零，不报错

    def test_ordinal_explicit_mapping(self) -> None:
        df = pd.DataFrame({"stage": ["I", "II", "III", "IV", "I"]})
        t = EncodeTransformer(method="ordinal", ordinal_columns={"stage": ["I", "II", "III", "IV"]})
        t.fit(df)
        out = t.transform(df)
        assert out["stage"].tolist() == [0, 1, 2, 3, 0]

    def test_auto_low_card_onehot_high_card_ordinal(self) -> None:
        df = pd.DataFrame(
            {
                "gender": ["男", "女"] * 10,
                "city": [f"C{i}" for i in range(20)],  # 20 > max_cardinality
            }
        )
        t = EncodeTransformer(method="auto", onehot_max_cardinality=5)
        t.fit(df)
        out = t.transform(df)
        assert any(c.startswith("gender_") for c in out.columns)
        assert out["city"].dtype != object  # 高基数 → 序数化

    def test_high_card_unknown_ordinal_is_sentinel(self) -> None:
        train = pd.DataFrame({"city": [f"C{i}" for i in range(20)]})
        val = pd.DataFrame({"city": ["NEW"]})
        t = EncodeTransformer(method="auto", onehot_max_cardinality=5)
        t.fit(train)
        out = t.transform(val)
        assert out["city"].iloc[0] == -1  # 未见类别 → 哨兵值


class TestScale:
    def test_standard(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0], "s": ["a"] * 5})
        t = ScaleTransformer(method="standard")
        t.fit(df)
        out = t.transform(df)
        assert out["x"].mean() == pytest.approx(0.0, abs=1e-9)
        assert out["x"].std(ddof=0) == pytest.approx(1.0)
        assert out["s"].tolist() == ["a"] * 5  # 非数值列不动

    def test_minmax(self) -> None:
        df = pd.DataFrame({"x": [0.0, 5.0, 10.0]})
        t = ScaleTransformer(method="minmax")
        t.fit(df)
        out = t.transform(df)
        assert out["x"].tolist() == [0.0, 0.5, 1.0]

    def test_robust(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 100.0]})
        t = ScaleTransformer(method="robust")
        t.fit(df)
        out = t.transform(df)
        # 中位数 2.5 → 2.0 缩放后 < 0，100 → 远大于 0
        assert out["x"].iloc[1] < 0 < out["x"].iloc[3]

    def test_transform_uses_train_params(self) -> None:
        train = pd.DataFrame({"x": [0.0, 10.0]})
        val = pd.DataFrame({"x": [5.0]})
        t = ScaleTransformer(method="minmax")
        t.fit(train)
        out = t.transform(val)
        assert out["x"].iloc[0] == pytest.approx(0.5)  # 用训练集 min/max

    def test_single_value_column(self) -> None:
        df = pd.DataFrame({"x": [3.0, 3.0, 3.0]})
        t = ScaleTransformer(method="standard")
        t.fit(df)
        out = t.transform(df)
        assert out["x"].tolist() == [0.0, 0.0, 0.0]  # 方差 0 → 全零，不产生 NaN


class TestSklearnPipelineCompat:
    def test_pipeline_chain(self, train_df: pd.DataFrame) -> None:
        pipe = Pipeline(
            [
                ("missing", MissingTransformer(default="median")),
                ("encode", EncodeTransformer(method="onehot")),
                ("scale", ScaleTransformer(method="standard")),
            ]
        )
        out = pipe.fit_transform(train_df.drop(columns=["all_nan"]))
        assert isinstance(out, pd.DataFrame)
        assert out.isna().sum().sum() == 0
        # 统计量可从命名步骤取回（Snapshot 用）
        assert pipe.named_steps["scale"].statistics_["columns"]
