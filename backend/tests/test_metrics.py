"""T5.2 统一 metrics 模块（docs/07 §5、docs/19）。

DoD：分类/生存/回归三任务类型的指标与官方库实现对拍一致（±1e-6）——
AUC vs sklearn、C-index vs sksurv/lifelines、IBS vs sksurv、RMSE/MAE/R² vs sklearn。
指标统一由 metrics 模块计算，模型适配器只输出预测值（风险分/概率/预测值）。
"""

import numpy as np
import pytest
from app.engines.comparison.metrics import (
    classification_metrics,
    regression_metrics,
    survival_metrics,
)
from lifelines.utils import concordance_index as lifelines_c_index
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sksurv.metrics import (
    concordance_index_censored,
    integrated_brier_score,
)
from sksurv.util import Surv


def _classification_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    y_true = rng.integers(0, 2, size=200)
    y_prob = np.clip(0.2 + 0.6 * y_true + rng.normal(0, 0.15, size=200), 0.0, 1.0)
    return y_true, y_prob


class TestClassificationMetrics:
    def test_matches_sklearn(self) -> None:
        y_true, y_prob = _classification_data()
        m = classification_metrics(y_true, y_prob)
        y_pred = (y_prob >= 0.5).astype(int)
        assert m["auc"] == pytest.approx(roc_auc_score(y_true, y_prob), abs=1e-6)
        assert m["accuracy"] == pytest.approx(accuracy_score(y_true, y_pred), abs=1e-6)
        assert m["precision"] == pytest.approx(
            precision_score(y_true, y_pred, zero_division=0), abs=1e-6
        )
        assert m["recall"] == pytest.approx(recall_score(y_true, y_pred, zero_division=0), abs=1e-6)
        assert m["f1"] == pytest.approx(f1_score(y_true, y_pred, zero_division=0), abs=1e-6)
        assert m["brier"] == pytest.approx(brier_score_loss(y_true, y_prob), abs=1e-6)
        assert m["pr_auc"] == pytest.approx(average_precision_score(y_true, y_prob), abs=1e-6)

    def test_perfect_prediction(self) -> None:
        y_true = np.array([0, 0, 1, 1])
        y_prob = np.array([0.05, 0.1, 0.9, 0.95])
        m = classification_metrics(y_true, y_prob)
        assert m["auc"] == pytest.approx(1.0)
        assert m["accuracy"] == pytest.approx(1.0)
        assert m["brier"] == pytest.approx(0.00625, abs=1e-6)

    def test_non_binary_rejected(self) -> None:
        with pytest.raises(ValueError, match="二分类"):
            classification_metrics(np.array([0, 1, 2, 1]), np.array([0.1, 0.5, 0.4, 0.9]))

    def test_length_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="长度"):
            classification_metrics(np.array([0, 1]), np.array([0.1, 0.5, 0.9]))


class TestRegressionMetrics:
    def test_matches_sklearn(self) -> None:
        rng = np.random.default_rng(42)
        y_true = rng.normal(50, 10, size=150)
        y_pred = y_true + rng.normal(0, 3, size=150)
        m = regression_metrics(y_true, y_pred)
        assert m["rmse"] == pytest.approx(
            float(np.sqrt(mean_squared_error(y_true, y_pred))), abs=1e-6
        )
        assert m["mae"] == pytest.approx(mean_absolute_error(y_true, y_pred), abs=1e-6)
        assert m["r2"] == pytest.approx(r2_score(y_true, y_pred), abs=1e-6)

    def test_perfect_prediction(self) -> None:
        y = np.array([1.0, 2.5, 3.7])
        m = regression_metrics(y, y)
        assert m["rmse"] == pytest.approx(0.0)
        assert m["mae"] == pytest.approx(0.0)
        assert m["r2"] == pytest.approx(1.0)


class TestSurvivalMetrics:
    def _data(self) -> dict[str, np.ndarray]:
        rng = np.random.default_rng(42)
        n_train, n_test = 120, 60
        time_train = rng.uniform(1, 100, size=n_train)
        event_train = rng.random(n_train) < 0.7
        time_test = rng.uniform(1, 100, size=n_test)
        event_test = rng.random(n_test) < 0.7
        risk = rng.normal(0, 1, size=n_test)  # 风险分：越大风险越高
        # IBS 时间网格须在删失分布可估范围内（sksurv 要求 ≤ 最大观测时间）
        all_times = np.concatenate([time_train, time_test])
        times = np.quantile(all_times, np.linspace(0.1, 0.9, 10))
        # 简单指数生存函数估计：S(t) = exp(-t / (50 * exp(risk)))
        surv = np.exp(-times[None, :] / (50.0 * np.exp(risk)[:, None]))
        return {
            "time_train": time_train,
            "event_train": event_train,
            "time_test": time_test,
            "event_test": event_test,
            "risk": risk,
            "times": times,
            "surv": surv,
        }

    def test_c_index_matches_sksurv_and_lifelines(self) -> None:
        d = self._data()
        m = survival_metrics(event_test=d["event_test"], time_test=d["time_test"], risk=d["risk"])
        expected = concordance_index_censored(d["event_test"], d["time_test"], d["risk"])[0]
        assert m["c_index"] == pytest.approx(expected, abs=1e-6)
        # lifelines 约定「预测值越大生存越久」，故传 -risk
        expected_ll = lifelines_c_index(d["time_test"], -d["risk"], d["event_test"])
        assert m["c_index"] == pytest.approx(expected_ll, abs=1e-6)

    def test_ibs_matches_sksurv(self) -> None:
        d = self._data()
        m = survival_metrics(
            event_train=d["event_train"],
            time_train=d["time_train"],
            event_test=d["event_test"],
            time_test=d["time_test"],
            risk=d["risk"],
            surv_pred=d["surv"],
            times=d["times"],
        )
        surv_train = Surv.from_arrays(d["event_train"], d["time_train"])
        in_range = d["time_test"] <= d["time_train"].max()
        surv_test = Surv.from_arrays(d["event_test"][in_range], d["time_test"][in_range])
        expected = integrated_brier_score(surv_train, surv_test, d["surv"][in_range], d["times"])
        assert m["ibs"] == pytest.approx(expected, abs=1e-6)

    def test_ibs_omitted_without_surv_pred(self) -> None:
        d = self._data()
        m = survival_metrics(event_test=d["event_test"], time_test=d["time_test"], risk=d["risk"])
        assert "ibs" not in m

    def test_ibs_requires_train_data(self) -> None:
        d = self._data()
        with pytest.raises(ValueError, match="训练集"):
            survival_metrics(
                event_test=d["event_test"],
                time_test=d["time_test"],
                risk=d["risk"],
                surv_pred=d["surv"],
                times=d["times"],
            )
