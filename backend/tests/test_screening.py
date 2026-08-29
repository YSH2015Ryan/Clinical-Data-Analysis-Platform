"""T6.10 单因素筛选 + 亚组分析引擎测试（先行，对应 docs/19）。

所有统计量必须真实计算（红线8）：p 值、效应量、CI 来自 scipy/statsmodels/lifelines。
"""

import numpy as np
import pandas as pd
import pytest
from app.engines.screening import subgroup_analysis, univariate_screen


def _classification_df(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    age = rng.normal(60, 10, n)
    # risk 与结局强相关；noise 无关
    risk = rng.normal(0, 1, n) + age * 0.05
    logit = -8 + 0.12 * age + 1.2 * (risk > risk.mean())
    y = (rng.uniform(0, 1, n) < 1 / (1 + np.exp(-logit))).astype(int)
    return pd.DataFrame(
        {
            "outcome": y,
            "age": age,
            "risk_score": risk,
            "noise": rng.normal(0, 1, n),
            "sex": rng.integers(0, 2, n),
        }
    )


def _survival_df(n: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    age = rng.normal(60, 10, n)
    hazard = np.exp(0.05 * (age - 60))
    time = rng.exponential(100 / hazard)
    event = (rng.uniform(0, 1, n) < 0.7).astype(int)
    return pd.DataFrame({"time": time, "event": event, "age": age, "noise": rng.normal(0, 1, n)})


def _regression_df(n: int = 150, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dose = rng.uniform(0, 100, n)
    y = 5 + 0.3 * dose + rng.normal(0, 10, n)
    return pd.DataFrame({"y": y, "dose": dose, "noise": rng.normal(0, 1, n)})


class TestUnivariateClassification:
    def test_strong_feature_selected(self) -> None:
        result = univariate_screen(
            _classification_df(), task_type="classification", label_col="outcome"
        )
        assert result["task_type"] == "classification"
        selected = result["selected_features"]
        assert "age" in selected
        assert "noise" not in selected

    def test_rows_sorted_by_p_and_real_values(self) -> None:
        result = univariate_screen(
            _classification_df(), task_type="classification", label_col="outcome"
        )
        rows = result["rows"]
        pvals = [r["p_value"] for r in rows]
        assert pvals == sorted(pvals)
        assert all(0.0 <= p <= 1.0 for p in pvals)
        assert all(r["n_used"] > 0 for r in rows)
        # outcome 自身不得出现在特征行
        assert "outcome" not in [r["feature"] for r in rows]

    def test_categorical_feature_chi2(self) -> None:
        df = _classification_df()
        df["site"] = [f"s{i % 3}" for i in range(len(df))]  # 3 水平 → 卡方
        result = univariate_screen(df, task_type="classification", label_col="outcome")
        site_row = next(r for r in result["rows"] if r["feature"] == "site")
        assert "卡方" in site_row["test"]
        sex_row = next(r for r in result["rows"] if r["feature"] == "sex")
        assert sex_row["test"] == "Fisher 精确检验"  # 2x2 用精确检验

    def test_alpha_threshold_respected(self) -> None:
        df = _classification_df()
        strict = univariate_screen(df, task_type="classification", label_col="outcome", alpha=1e-9)
        assert strict["selected_features"] == []

    def test_missing_label_raises(self) -> None:
        with pytest.raises(ValueError):
            univariate_screen(_classification_df(), task_type="classification")


class TestUnivariateSurvival:
    def test_cox_per_feature(self) -> None:
        result = univariate_screen(
            _survival_df(), task_type="survival", time_col="time", event_col="event"
        )
        rows = {r["feature"]: r for r in result["rows"]}
        assert "age" in rows and "noise" in rows
        age = rows["age"]
        assert "Cox" in age["test"]
        assert age["effect"] is not None and age["effect"] > 1.0  # HR>1（年龄越大风险越高）
        assert "age" in result["selected_features"]

    def test_requires_time_event(self) -> None:
        with pytest.raises(ValueError):
            univariate_screen(_survival_df(), task_type="survival", time_col="time")


class TestUnivariateRegression:
    def test_correlation_screen(self) -> None:
        result = univariate_screen(_regression_df(), task_type="regression", label_col="y")
        rows = {r["feature"]: r for r in result["rows"]}
        assert rows["dose"]["p_value"] < 0.05
        assert rows["noise"]["p_value"] > 0.01
        assert "dose" in result["selected_features"]
        assert rows["dose"]["effect"] is not None  # 相关系数

    def test_feature_cap(self) -> None:
        rng = np.random.default_rng(1)
        data = {"y": rng.normal(0, 1, 60)}
        for i in range(60):
            data[f"x{i}"] = rng.normal(0, 1, 60)
        result = univariate_screen(pd.DataFrame(data), task_type="regression", label_col="y")
        assert len(result["rows"]) <= 50


class TestSubgroupAnalysis:
    def test_binary_exposure_classification(self) -> None:
        df = _classification_df(n=300)
        df["treated"] = (df["risk_score"] > df["risk_score"].median()).astype(int)
        result = subgroup_analysis(
            df,
            task_type="classification",
            exposure="treated",
            label_col="outcome",
            subgroup_vars=["sex"],
        )
        assert result["exposure"] == "treated"
        sub = result["subgroups"][0]
        assert sub["variable"] == "sex"
        assert len(sub["levels"]) == 2
        for lv in sub["levels"]:
            assert lv["n"] > 0
            assert lv["effect"] is not None  # OR
            assert lv["ci_lower"] is not None and lv["ci_upper"] is not None
        assert sub["interaction_p"] is not None
        assert 0.0 <= sub["interaction_p"] <= 1.0

    def test_continuous_exposure_regression(self) -> None:
        df = _regression_df(n=200)
        df["age_group"] = pd.cut(np.linspace(0, 1, 200), bins=3, labels=["T1", "T2", "T3"]).astype(
            str
        )
        result = subgroup_analysis(
            df,
            task_type="regression",
            exposure="dose",
            label_col="y",
            subgroup_vars=["age_group"],
        )
        sub = result["subgroups"][0]
        assert len(sub["levels"]) == 3
        for lv in sub["levels"]:
            assert lv["effect"] is not None  # β

    def test_survival_subgroup_hr(self) -> None:
        df = _survival_df(n=200)
        df["sex"] = np.random.default_rng(5).integers(0, 2, 200)
        df["treated"] = (df["age"] > 60).astype(int)
        result = subgroup_analysis(
            df,
            task_type="survival",
            exposure="treated",
            time_col="time",
            event_col="event",
            subgroup_vars=["sex"],
        )
        sub = result["subgroups"][0]
        assert all(lv["effect"] is not None and lv["effect"] > 0 for lv in sub["levels"])

    def test_invalid_subgroup_var_raises(self) -> None:
        df = _classification_df()
        with pytest.raises(ValueError):
            subgroup_analysis(
                df,
                task_type="classification",
                exposure="age",
                label_col="outcome",
                subgroup_vars=["nonexistent"],
            )

    def test_too_many_levels_raises(self) -> None:
        df = _classification_df(n=200)
        df["many"] = [f"g{i % 10}" for i in range(200)]
        with pytest.raises(ValueError):
            subgroup_analysis(
                df,
                task_type="classification",
                exposure="sex",
                label_col="outcome",
                subgroup_vars=["many"],
            )
