"""T3.3 预处理步骤单测：feature_select / derive（docs/06 §3）。

安全红线（CLAUDE.md §7、docs/06）：derive 走 simpleeval 白名单求值，
拒绝任意代码执行——安全用例是本文件的 DoD 核心。
"""

import numpy as np
import pandas as pd
import pytest
from app.engines.preprocess_steps import (
    DeriveTransformer,
    EncodeTransformer,
    FeatureSelectTransformer,
    MissingTransformer,
    ScaleTransformer,
)
from sklearn.pipeline import Pipeline


class TestFeatureSelectVariance:
    def test_drops_zero_variance(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "const": [5.0] * 4})
        t = FeatureSelectTransformer(method="variance_threshold", threshold=0.0)
        t.fit(df)
        out = t.transform(df)
        assert "const" not in out.columns
        assert "x" in out.columns
        assert "const" in t.statistics_["dropped"]

    def test_threshold_keeps_high_variance(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [1.0, 1.1, 0.9, 1.05]})
        t = FeatureSelectTransformer(method="variance_threshold", threshold=0.5)
        t.fit(df)
        out = t.transform(df)
        assert "x" in out.columns
        assert "y" not in out.columns

    def test_transform_uses_train_dropped(self) -> None:
        train = pd.DataFrame({"x": [1.0, 2.0, 3.0], "const": [5.0] * 3})
        val = pd.DataFrame({"x": [9.0], "const": [7.0]})  # 验证集里 const 变了也要删
        t = FeatureSelectTransformer(method="variance_threshold")
        t.fit(train)
        out = t.transform(val)
        assert out.columns.tolist() == ["x"]


class TestFeatureSelectCorrelation:
    def test_drops_correlated_copy(self) -> None:
        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0, 5.0],
                "b": [2.0, 4.0, 6.0, 8.0, 10.0],
                "c": [5.0, 1.0, 4.0, 2.0, 3.0],
            }
        )
        t = FeatureSelectTransformer(method="correlation", threshold=0.95)
        t.fit(df)
        out = t.transform(df)
        assert len(out.columns) == 2  # a/b 完全相关 → 删其一
        assert "c" in out.columns

    def test_default_threshold_when_zero(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [1.1, 1.9, 3.05, 3.95]})
        t = FeatureSelectTransformer(method="correlation")  # threshold=0 → 默认 0.95
        t.fit(df)
        out = t.transform(df)
        assert len(out.columns) == 1


class TestFeatureSelectUnivariate:
    def test_requires_y(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        t = FeatureSelectTransformer(method="univariate", threshold=1.0)
        with pytest.raises(ValueError, match="y"):
            t.fit(df)

    def test_keeps_signal_drops_noise(self) -> None:
        rng = np.random.default_rng(42)
        y = rng.normal(0, 1, 200)
        df = pd.DataFrame({"signal": y + rng.normal(0, 0.01, 200), "noise": rng.normal(0, 1, 200)})
        t = FeatureSelectTransformer(method="univariate", threshold=10.0)
        t.fit(df, y)
        out = t.transform(df)
        assert "signal" in out.columns
        assert "noise" not in out.columns
        assert t.statistics_["scores"]["signal"] > t.statistics_["scores"]["noise"]


class TestFeatureSelectLasso:
    def test_requires_y(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        t = FeatureSelectTransformer(method="lasso")
        with pytest.raises(ValueError, match="y"):
            t.fit(df)

    def test_lasso_zero_coef_dropped(self) -> None:
        rng = np.random.default_rng(0)
        x1 = rng.uniform(0, 1, 100)
        y = 3.0 * x1 + rng.normal(0, 0.01, 100)
        df = pd.DataFrame({"x1": x1, "x2": rng.uniform(0, 1, 100)})
        t = FeatureSelectTransformer(method="lasso", threshold=0.01)
        t.fit(df, y)
        out = t.transform(df)
        assert "x1" in out.columns
        assert "x2" not in out.columns


class TestDerive:
    def test_arithmetic_expression(self) -> None:
        df = pd.DataFrame({"os_months": [12.0, 24.0, 36.0]})
        t = DeriveTransformer(expressions=[{"name": "followup_years", "expr": "os_months / 12"}])
        t.fit(df)
        out = t.transform(df)
        assert out["followup_years"].tolist() == [1.0, 2.0, 3.0]
        assert "os_months" in out.columns  # 原列保留

    def test_whitelist_function_log(self) -> None:
        df = pd.DataFrame({"wbc": [1.0, np.e, np.e**2]})
        t = DeriveTransformer(expressions=[{"name": "log_wbc", "expr": "log(wbc)"}])
        t.fit(df)
        out = t.transform(df)
        assert out["log_wbc"].tolist() == pytest.approx([0.0, 1.0, 2.0])

    def test_bad_expr_fails_at_fit(self) -> None:
        df = pd.DataFrame({"x": [1.0]})
        t = DeriveTransformer(expressions=[{"name": "bad", "expr": "x +* 1"}])
        with pytest.raises(ValueError, match="表达式"):
            t.fit(df)

    def test_unknown_column_raises(self) -> None:
        df = pd.DataFrame({"x": [1.0]})
        t = DeriveTransformer(expressions=[{"name": "bad", "expr": "ghost * 2"}])
        with pytest.raises(ValueError, match="ghost"):
            t.fit(df)

    @pytest.mark.parametrize(
        "evil",
        [
            "__import__('os').system('echo pwned')",  # 导入+系统调用
            "open('/etc/passwd').read()",  # 文件读取
            "x.__class__.__bases__",  # 属性逃逸
            "eval('1+1')",  # 内建 eval
            "(lambda: 1)()",  # lambda 定义
            "10 ** 10 ** 8",  # 指数 DoS
        ],
    )
    def test_rejects_arbitrary_code(self, evil: str) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0]})
        t = DeriveTransformer(expressions=[{"name": "evil", "expr": evil}])
        with pytest.raises(ValueError, match="表达式"):
            t.fit(df)

    def test_only_whitelisted_functions(self) -> None:
        df = pd.DataFrame({"x": [1.0]})
        t = DeriveTransformer(expressions=[{"name": "bad", "expr": "exec('x')"}])
        with pytest.raises(ValueError, match="表达式"):
            t.fit(df)

    def test_deterministic_across_calls(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        t = DeriveTransformer(expressions=[{"name": "c", "expr": "a * b + sqrt(a)"}])
        t.fit(df)
        out1 = t.transform(df)
        out2 = t.transform(df)
        pd.testing.assert_frame_equal(out1, out2)


class TestFullPipelineChain:
    def test_all_six_steps(self) -> None:
        df = pd.DataFrame(
            {
                "os_months": [12.0, 24.0, np.nan, 48.0, 60.0, 6.0],
                "wbc": [5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
                "const": [1.0] * 6,
                "gender": ["男", "女", "男", "女", "男", "女"],
            }
        )
        pipe = Pipeline(
            [
                ("missing", MissingTransformer(default="median")),
                ("encode", EncodeTransformer(method="onehot")),
                ("scale", ScaleTransformer(method="standard")),
                (
                    "derive",
                    DeriveTransformer(expressions=[{"name": "wbc_sq", "expr": "wbc * wbc"}]),
                ),
                ("select", FeatureSelectTransformer(method="variance_threshold")),
            ]
        )
        out = pipe.fit_transform(df)
        assert isinstance(out, pd.DataFrame)
        assert out.isna().sum().sum() == 0
        assert "const" not in out.columns  # 方差 0 被删除
        assert "wbc_sq" in out.columns
