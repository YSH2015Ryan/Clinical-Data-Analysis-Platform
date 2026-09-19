"""P1-15 统计引擎 Ground Truth 验证（updateplan §87，Dataset I）。

与 §80–81 回归测试互补：那些验证引擎「诚实」（能发现已知问题）；
本模块验证引擎「算得对」——已知真实效应量的模拟数据上：

1. 真实效应恢复：OR / HR / β 点估计收敛到真值，95%CI 覆盖真值；
2. 参考实现对拍：引擎输出 vs statsmodels / lifelines / scikit-learn
   直接计算，相对误差 < 1%（§87 容差阈值）；
3. 指标真值：AUC 手算对拍（不经 sklearn）、校准斜率收敛到已知真值。

纳入 CI 回归测试（§87 要求）；lifelines 相关用例在缺依赖环境自动跳过。
"""

import numpy as np
import pytest
from app.engines.adjustment import adjusted_association
from app.engines.screening import _or_2x2

from tests.fixtures.ground_truth import (
    make_binary_ground_truth,
    make_miscalibrated_probabilities,
    make_regression_ground_truth,
    make_survival_ground_truth,
)

_REL_TOL = 0.01  # §87：与参考实现对拍的相对误差阈值 1%


def _rel_err(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-12)


def _classification_metrics():
    """metrics 引擎模块级依赖 sksurv（无 Windows wheel 的环境缺装）→ 惰性导入 + 跳过。"""
    pytest.importorskip("sksurv")
    from app.engines.comparison.metrics import classification_metrics

    return classification_metrics


# ---------------------------------------------------------------- 真实效应恢复


class TestTrueEffectRecovery:
    """大样本模拟数据上，引擎估计须收敛到已知真实效应（CI 覆盖 + 点估计容差）。"""

    def test_true_or_recovered(self) -> None:
        df, truth = make_binary_ground_truth()
        result = adjusted_association(
            df,
            task_type="classification",
            exposure="treatment",
            confounders=["age"],
            label_col="outcome",
        )
        adj = result["adjusted"]
        assert adj["effect_label"] == "OR"
        assert _rel_err(adj["effect"], truth["true_or"]) < 0.10
        assert adj["ci_lower"] < truth["true_or"] < adj["ci_upper"]

    def test_true_or_recovered_unadjusted(self) -> None:
        """暴露与协变量独立 → 未校正 OR 同样收敛到真值（无混杂时不可「校正出」假效应）。"""
        df, truth = make_binary_ground_truth()
        result = adjusted_association(
            df,
            task_type="classification",
            exposure="treatment",
            confounders=["age"],
            label_col="outcome",
        )
        assert _rel_err(result["unadjusted"]["effect"], truth["true_or"]) < 0.10

    def test_true_beta_recovered(self) -> None:
        df, truth = make_regression_ground_truth()
        result = adjusted_association(
            df,
            task_type="regression",
            exposure="dose",
            confounders=["weight"],
            label_col="y",
        )
        adj = result["adjusted"]
        assert adj["effect_label"] == "β"
        # n=2000、SE(β)≈0.011：§87 的 1% 容差对线性回归可直接成立
        assert _rel_err(adj["effect"], truth["true_beta_dose"]) < _REL_TOL
        assert adj["ci_lower"] < truth["true_beta_dose"] < adj["ci_upper"]

    def test_true_hr_recovered(self) -> None:
        pytest.importorskip("lifelines")
        df, truth = make_survival_ground_truth()
        result = adjusted_association(
            df,
            task_type="survival",
            exposure="treated",
            confounders=["age"],
            time_col="time",
            event_col="event",
        )
        adj = result["adjusted"]
        assert adj["effect_label"] == "HR"
        assert _rel_err(adj["effect"], truth["true_hr"]) < 0.15
        assert adj["ci_lower"] < truth["true_hr"] < adj["ci_upper"]


# ---------------------------------------------------------------- 参考实现对拍


class TestReferenceAgreement:
    """引擎输出与官方库直接计算对拍（§87：相对误差 < 1%；docs/19 ±1e-6 精神）。"""

    def test_or_2x2_matches_statsmodels(self) -> None:
        """手写 _or_2x2（log 法 CI）点估计 = statsmodels Logit MLE（2x2 饱和模型）。"""
        import statsmodels.api as sm

        df, _ = make_binary_ground_truth(n=2000)
        y = df["outcome"].to_numpy(dtype=float)
        or_engine, lo, hi = _or_2x2(df, "treatment", y)
        x = sm.add_constant(df["treatment"].to_numpy(dtype=float))
        fit = sm.Logit(y, x).fit(disp=0)
        or_ref = float(np.exp(fit.params[1]))
        assert _rel_err(or_engine, or_ref) < _REL_TOL
        assert lo < or_engine < hi

    def test_adjusted_or_matches_statsmodels_direct(self) -> None:
        """引擎（含缺失剔除/哑变量接线）输出 = statsmodels 直接拟合。"""
        import statsmodels.api as sm

        df, _ = make_binary_ground_truth()
        result = adjusted_association(
            df,
            task_type="classification",
            exposure="treatment",
            confounders=["age"],
            label_col="outcome",
        )
        x = sm.add_constant(df[["treatment", "age"]].astype(float))
        fit = sm.Logit(df["outcome"].to_numpy(dtype=float), x).fit(disp=0)
        or_ref = float(np.exp(fit.params["treatment"]))
        assert _rel_err(result["adjusted"]["effect"], or_ref) < _REL_TOL
        p_ref = float(fit.pvalues["treatment"])
        assert _rel_err(result["adjusted"]["p_value"], p_ref) < _REL_TOL

    def test_categorical_confounder_matches_statsmodels(self) -> None:
        """分类混杂哑变量化（drop_first）与 statsmodels 手工哑变量对拍。"""
        import statsmodels.api as sm

        df, _ = make_binary_ground_truth(n=3000)
        df["site"] = np.where(df["age"] > 65, "B", "A")
        result = adjusted_association(
            df,
            task_type="classification",
            exposure="treatment",
            confounders=["age", "site"],
            label_col="outcome",
        )
        import pandas as pd

        dummies = (
            pd.get_dummies(df["site"].astype("string"), prefix="site", drop_first=True)
            .astype(float)
            .to_numpy()
        )
        x = sm.add_constant(
            np.column_stack([df["treatment"].to_numpy(float), df["age"].to_numpy(float), dummies])
        )
        fit = sm.Logit(df["outcome"].to_numpy(dtype=float), x).fit(disp=0)
        or_ref = float(np.exp(fit.params[1]))
        assert _rel_err(result["adjusted"]["effect"], or_ref) < _REL_TOL

    def test_adjusted_hr_matches_lifelines_direct(self) -> None:
        pytest.importorskip("lifelines")
        import pandas as pd
        from lifelines import CoxPHFitter

        df, _ = make_survival_ground_truth()
        result = adjusted_association(
            df,
            task_type="survival",
            exposure="treated",
            confounders=["age"],
            time_col="time",
            event_col="event",
        )
        ref_df = df[["time", "event", "treated", "age"]].astype(float)
        cph = CoxPHFitter().fit(ref_df, duration_col="time", event_col="event")
        hr_ref = float(np.exp(cph.summary.loc["treated", "coef"]))
        assert _rel_err(result["adjusted"]["effect"], hr_ref) < _REL_TOL
        p_ref = float(cph.summary.loc["treated", "p"])
        assert _rel_err(result["adjusted"]["p_value"], p_ref) < _REL_TOL
        assert pd.notna(result["adjusted"]["ci_lower"])


# ---------------------------------------------------------------- 指标真值


class TestMetricGroundTruth:
    """AUC / 校准斜率的已知真值验证（AUC 手算对拍，不经 sklearn）。"""

    def test_auc_hand_computed(self) -> None:
        """y=[0,0,1,1], p=[0.1,0.4,0.35,0.8]：4 个正负对中 3 个有序 → AUC=0.75。"""
        metrics = _classification_metrics()([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8])
        assert metrics["auc"] == pytest.approx(0.75, abs=1e-12)

    def test_auc_perfect_and_chance(self) -> None:
        perfect = _classification_metrics()([0, 0, 1, 1], [0.2, 0.3, 0.7, 0.9])
        assert perfect["auc"] == pytest.approx(1.0, abs=1e-12)
        chance = _classification_metrics()([0, 1] * 50, [0.5] * 100)
        assert chance["auc"] == pytest.approx(0.5, abs=1e-12)

    def test_auc_matches_sklearn(self) -> None:
        """大样本随机数据上与 sklearn roc_auc_score 对拍（docs/19 ±1e-6）。"""
        from sklearn.metrics import roc_auc_score

        rng = np.random.default_rng(87)
        y = rng.binomial(1, 0.3, 5000)
        p = np.clip(0.3 + 0.2 * y + rng.normal(0, 0.15, 5000), 1e-4, 1 - 1e-4)
        metrics = _classification_metrics()(y, p)
        assert metrics["auc"] == pytest.approx(float(roc_auc_score(y, p)), abs=1e-6)

    def test_calibration_slope_recovers_truth(self) -> None:
        """预测 logit 放大 2 倍 → 校准斜率真值 0.5、截距真值 0。"""
        y, p, true_slope = make_miscalibrated_probabilities()
        metrics = _classification_metrics()(y, p)
        assert metrics["calibration_slope"] == pytest.approx(true_slope, abs=0.05)
        assert metrics["calibration_intercept"] == pytest.approx(0.0, abs=0.05)
