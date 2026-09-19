"""§25 Leakage Experiment Mode（P1 延伸，先行测试）。

A/B/C/D 变量集敏感性实验：A=全部变量，B=移除可疑泄漏变量，C=移除日期变量，
D=仅基线临床变量（确定性启发式：非可疑/非日期/非近 ID 的普通测量列）。
比较 AUC/PR-AUC/Sens/Spec/Calibration（分类）或 RMSE/R²（回归）；
性能大幅下降 → 固定文案提示「性能很可能由泄漏驱动」。全部数值真实计算（红线 8）。
"""

import numpy as np
import pandas as pd
import pytest
from app.engines.leakage import inspect_leakage
from app.engines.leakage_experiment import plan_variable_sets, run_leakage_experiment


def _leaky_df(n: int = 600, seed: int = 25) -> pd.DataFrame:
    """含已知泄漏：leak_copy 为结局的精确复制（TARGET_PROXY，corr=1）+ admission_date 日期列。"""
    rng = np.random.default_rng(seed)
    age = rng.normal(60, 10, n)
    bmi = rng.normal(24, 3, n)
    logit = -2 + 0.04 * (age - 60) + 0.1 * (bmi - 24)
    y = (rng.uniform(0, 1, n) < 1 / (1 + np.exp(-logit))).astype(int)
    return pd.DataFrame(
        {
            "patient_id": [f"P{i:04d}" for i in range(n)],
            "age": age,
            "bmi": bmi,
            "admission_date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "leak_copy": y.copy(),
            "outcome": y,
        }
    )


class TestPlanVariableSets:
    def test_four_sets_membership(self) -> None:
        df = _leaky_df()
        inspection = inspect_leakage(df, target_col="outcome")
        sets = plan_variable_sets(
            df, target_col="outcome", inspection=inspection
        )
        a = sets["A_all"]["features"]
        assert {"age", "bmi", "admission_date", "leak_copy"} <= set(a)
        assert "outcome" not in a and "patient_id" not in a  # 结局/ID 不入特征池
        assert "leak_copy" not in sets["B_no_suspicious"]["features"]  # B 移除可疑
        assert "admission_date" not in sets["C_no_dates"]["features"]  # C 移除日期
        d = sets["D_baseline"]["features"]
        assert "leak_copy" not in d and "admission_date" not in d
        assert "patient_id" not in d  # 近 ID 列排除
        assert set(d) <= {"age", "bmi"}

    def test_removed_features_recorded(self) -> None:
        """每个集合须记录被移除的变量（报告可追溯）。"""
        df = _leaky_df()
        sets = plan_variable_sets(
            df, target_col="outcome", inspection=inspect_leakage(df, target_col="outcome")
        )
        assert "leak_copy" in sets["B_no_suspicious"]["removed"]
        assert "admission_date" in sets["C_no_dates"]["removed"]


class TestRunExperiment:
    def test_leaky_signal_exposed(self) -> None:
        """A（含泄漏）AUC≈1.0；B（移除泄漏）显著下降 → 文案提示泄漏驱动。"""
        df = _leaky_df()
        result = run_leakage_experiment(df, task_type="classification", target_col="outcome")
        by_key = {s["set_key"]: s for s in result["sets"]}
        assert by_key["A_all"]["metrics"]["auc"] > 0.99
        drop = by_key["A_all"]["metrics"]["auc"] - by_key["B_no_suspicious"]["metrics"]["auc"]
        assert drop > 0.1
        assert "泄漏" in result["interpretation"]
        # §25 指标清单
        for key in ("auc", "pr_auc", "sensitivity", "specificity", "calibration_slope"):
            assert key in by_key["A_all"]["metrics"]

    def test_clean_dataset_no_big_drop(self) -> None:
        """无泄漏数据：移除变量后性能无大幅下降 → 文案不指控泄漏。"""
        rng = np.random.default_rng(26)
        n = 500
        x1 = rng.normal(0, 1, n)
        x2 = rng.normal(0, 1, n)
        y = (rng.uniform(0, 1, n) < 1 / (1 + np.exp(-(x1 + x2)))).astype(int)
        df = pd.DataFrame({"x1": x1, "x2": x2, "outcome": y})
        result = run_leakage_experiment(df, task_type="classification", target_col="outcome")
        by_key = {s["set_key"]: s for s in result["sets"]}
        assert by_key["A_all"]["metrics"]["auc"] > 0.7
        assert "很可能由泄漏驱动" not in result["interpretation"]

    def test_regression_task_rmse(self) -> None:
        rng = np.random.default_rng(27)
        n = 400
        x = rng.normal(0, 1, n)
        y = 10 + 2 * x + rng.normal(0, 3, n)
        df = pd.DataFrame({"x": x, "leak": y.copy(), "y": y})  # leak = 结局精确复制
        result = run_leakage_experiment(df, task_type="regression", target_col="y")
        by_key = {s["set_key"]: s for s in result["sets"]}
        assert by_key["A_all"]["metrics"]["rmse"] < by_key["B_no_suspicious"]["metrics"]["rmse"]
        assert "r2" in by_key["A_all"]["metrics"]

    def test_deterministic(self) -> None:
        df = _leaky_df()
        r1 = run_leakage_experiment(df, task_type="classification", target_col="outcome")
        r2 = run_leakage_experiment(df, task_type="classification", target_col="outcome")
        assert r1 == r2  # seed=42 纪律（CLAUDE.md 规范 6）

    def test_empty_set_skipped_with_note(self) -> None:
        """集合为空（如全部变量皆可疑）→ 该集合 note 说明而非崩溃。"""
        df = _leaky_df()
        df = df[["outcome", "leak_copy"]]  # 只剩结局 + 泄漏列
        result = run_leakage_experiment(df, task_type="classification", target_col="outcome")
        b = next(s for s in result["sets"] if s["set_key"] == "B_no_suspicious")
        assert b["metrics"] is None and b["note"]
