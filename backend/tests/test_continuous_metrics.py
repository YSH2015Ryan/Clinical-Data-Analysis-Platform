"""P1-14 连续型结局评价补齐（updateplan §44，先行测试）。

新增：Adjusted R²（须传 n_features）、MAPE（y_true 含 0 时 NaN——「适用时」）、
回归版 calibration-in-the-large（mean_bias 系统性偏倚）与回归校准斜率
（observed ~ predicted OLS 斜率）、残差图（residual vs fitted）。
所有数值由 sklearn/numpy 真实计算并与 statsmodels 对拍。
"""

import numpy as np
import pytest

from tests.fixtures.ground_truth import make_regression_ground_truth


def _regression_metrics():
    """metrics 引擎模块级依赖 sksurv → 惰性导入 + 缺依赖跳过（CI 全量运行）。"""
    pytest.importorskip("sksurv")
    from app.engines.comparison.metrics import regression_metrics

    return regression_metrics


class TestAdjustedR2:
    def test_matches_statsmodels(self) -> None:
        """与 statsmodels OLS rsquared_adj 对拍（±1e-9）。"""
        import statsmodels.api as sm

        df, _ = make_regression_ground_truth(n=500)
        x = sm.add_constant(df[["dose", "weight"]].astype(float))
        fit = sm.OLS(df["y"].to_numpy(float), x).fit()
        pred = fit.predict(x)
        metrics = _regression_metrics()(df["y"].to_numpy(float), pred, n_features=2)
        assert metrics["adjusted_r2"] == pytest.approx(float(fit.rsquared_adj), abs=1e-9)
        assert metrics["r2"] == pytest.approx(float(fit.rsquared), abs=1e-9)

    def test_perfect_prediction(self) -> None:
        y = np.arange(100.0)
        metrics = _regression_metrics()(y, y.copy(), n_features=5)
        assert metrics["adjusted_r2"] == pytest.approx(1.0)

    def test_nan_without_n_features(self) -> None:
        """未传 n_features → adjusted_r2 为 NaN（不可计算时不得虚构）。"""
        y = np.arange(10.0)
        metrics = _regression_metrics()(y, y + 1.0)
        assert np.isnan(metrics["adjusted_r2"])

    def test_nan_when_n_too_small(self) -> None:
        """n <= p+1 时分母非正 → NaN。"""
        y = np.array([1.0, 2.0, 3.0])
        metrics = _regression_metrics()(y, y.copy(), n_features=2)
        assert np.isnan(metrics["adjusted_r2"])


class TestMape:
    def test_hand_computed(self) -> None:
        """y=[100,200], pred=[110,190] → mean(0.1, 0.05)=0.075。"""
        metrics = _regression_metrics()([100.0, 200.0], [110.0, 190.0])
        assert metrics["mape"] == pytest.approx(0.075, abs=1e-12)

    def test_nan_when_y_true_contains_zero(self) -> None:
        """§44「MAPE（适用时）」：y_true 含 0 → NaN（除零无意义，不得虚构）。"""
        metrics = _regression_metrics()([0.0, 100.0], [5.0, 100.0])
        assert np.isnan(metrics["mape"])


class TestRegressionCalibration:
    def test_mean_bias_detects_systematic_overestimation(self) -> None:
        """calibration-in-the-large 回归版：系统性高估 5 → mean_bias=+5。"""
        y = np.linspace(10, 50, 200)
        metrics = _regression_metrics()(y, y + 5.0)
        assert metrics["mean_bias"] == pytest.approx(5.0, abs=1e-9)

    def test_calibration_slope_scaled_predictions(self) -> None:
        """预测值整体放大 2 倍 → observed ~ predicted 斜率 = 0.5。"""
        rng = np.random.default_rng(44)
        y = rng.normal(100, 20, 2000)
        metrics = _regression_metrics()(y, y * 2.0)
        assert metrics["calibration_slope"] == pytest.approx(0.5, abs=1e-9)

    def test_perfect_prediction_slope_one_bias_zero(self) -> None:
        y = np.linspace(0, 100, 500)
        metrics = _regression_metrics()(y, y.copy())
        assert metrics["calibration_slope"] == pytest.approx(1.0)
        assert metrics["mean_bias"] == pytest.approx(0.0, abs=1e-9)

    def test_constant_prediction_slope_nan(self) -> None:
        """预测无变异 → 斜率不可估计 → NaN。"""
        metrics = _regression_metrics()(np.arange(10.0), np.full(10, 5.0))
        assert np.isnan(metrics["calibration_slope"])


class TestResidualChart:
    def _rows(self) -> list[dict]:
        return [
            {
                "model_key": "lasso",
                "metrics": {"rmse": {"mean": 2.0}},
                "artifacts": {
                    "prediction_scatter": {
                        "y_true": [10.0, 20.0, 30.0, 40.0],
                        "y_pred": [12.0, 18.0, 33.0, 37.0],
                    }
                },
                "explainability": None,
            }
        ]

    def test_residual_chart_built_from_scatter(self) -> None:
        """残差图由 prediction_scatter 派生：fitted=y_pred，residual=y_true-y_pred。"""
        from app.engines.comparison.charts import build_comparison_charts

        charts = build_comparison_charts("regression", self._rows())
        kinds = [c["kind"] for c in charts]
        assert "residual_plot" in kinds
        residual = next(c for c in charts if c["kind"] == "residual_plot")
        series = residual["data"]["series"][0]
        assert series["model_key"] == "lasso"
        assert series["fitted"] == [12.0, 18.0, 33.0, 37.0]
        assert series["residuals"] == pytest.approx([-2.0, 2.0, -3.0, 3.0])

    def test_scatter_chart_still_first(self) -> None:
        from app.engines.comparison.charts import build_comparison_charts

        charts = build_comparison_charts("regression", self._rows())
        assert charts[0]["kind"] == "prediction_scatter"
