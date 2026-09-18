"""P1-12 混杂因素校正（updateplan §29，先行测试）。

研究者指定混杂清单（系统不猜测因果结构）；logistic/linear/Cox 按任务类型自动选择；
Unadjusted 与 Adjusted 并列展示；文案明确「调整后关联 ≠ 因果效应」（Principle 4）。
"""

import numpy as np
import pandas as pd
import pytest
from app.engines.adjustment import adjusted_association


def _confounded_clf(n: int = 800, seed: int = 11) -> pd.DataFrame:
    """暴露 treatment 与结局的原始关联完全由混杂 age 驱动：
    校正 age 后 OR 应回落至 1 附近，未校正 OR 显著偏离 1。"""
    rng = np.random.default_rng(seed)
    age = rng.normal(60, 12, n)
    treatment = (age + rng.normal(0, 8, n) > 62).astype(int)  # 高龄更易暴露
    logit = -2 + 0.06 * (age - 60)  # 结局只依赖 age
    y = (rng.uniform(0, 1, n) < 1 / (1 + np.exp(-logit))).astype(int)
    return pd.DataFrame({"age": age, "treatment": treatment, "outcome": y})


def _confounded_reg(n: int = 600, seed: int = 13) -> pd.DataFrame:
    """回归版：dose 与 y 的关联由混杂 weight 驱动。"""
    rng = np.random.default_rng(seed)
    weight = rng.normal(70, 15, n)
    dose = 30 + 0.5 * (weight - 70) + rng.normal(0, 5, n)
    y = 10 + 0.8 * (weight - 70) + rng.normal(0, 5, n)  # y 只依赖 weight
    return pd.DataFrame({"weight": weight, "dose": dose, "y": y})


class TestClassificationAdjustment:
    def test_adjusted_or_attenuates_to_null(self) -> None:
        result = adjusted_association(
            _confounded_clf(),
            task_type="classification",
            exposure="treatment",
            confounders=["age"],
            label_col="outcome",
        )
        unadj, adj = result["unadjusted"], result["adjusted"]
        assert unadj["effect_label"] == "OR"
        # 未校正：混杂驱动 → OR 显著 > 1
        assert unadj["effect"] > 1.2 and unadj["p_value"] < 0.05
        # 校正后：回落至 1 附近且 CI 覆盖 1
        assert abs(adj["effect"] - 1.0) < 0.35
        assert adj["ci_lower"] < 1.0 < adj["ci_upper"]
        assert adj["p_value"] > 0.05
        assert result["confounders"] == ["age"]
        assert result["n_used"] == 800

    def test_categorical_confounder_dummified(self) -> None:
        df = _confounded_clf()
        df["site"] = np.where(df["age"] > 65, "B", "A")  # 与结局相关的分类混杂
        result = adjusted_association(
            df,
            task_type="classification",
            exposure="treatment",
            confounders=["age", "site"],
            label_col="outcome",
        )
        assert result["adjusted"]["effect"] is not None
        assert result["confounders"] == ["age", "site"]


class TestRegressionAdjustment:
    def test_adjusted_beta_attenuates(self) -> None:
        result = adjusted_association(
            _confounded_reg(),
            task_type="regression",
            exposure="dose",
            confounders=["weight"],
            label_col="y",
        )
        unadj, adj = result["unadjusted"], result["adjusted"]
        assert unadj["effect_label"] == "β"
        assert unadj["p_value"] < 0.05  # 原始关联显著
        assert abs(adj["effect"]) < abs(unadj["effect"])  # 校正后衰减
        assert adj["p_value"] > 0.05


class TestSurvivalAdjustment:
    def test_adjusted_hr_attenuates(self) -> None:
        rng = np.random.default_rng(17)
        n = 800
        age = rng.normal(65, 10, n)
        treated = (age + rng.normal(0, 8, n) > 67).astype(int)
        hazard = np.exp(0.05 * (age - 65))  # 风险只依赖 age
        time = rng.exponential(100 / hazard)
        event = (rng.uniform(0, 1, n) < 0.8).astype(int)
        df = pd.DataFrame({"age": age, "treated": treated, "time": time, "event": event})
        result = adjusted_association(
            df,
            task_type="survival",
            exposure="treated",
            confounders=["age"],
            time_col="time",
            event_col="event",
        )
        unadj, adj = result["unadjusted"], result["adjusted"]
        assert unadj["effect_label"] == "HR"
        assert abs(np.log(adj["effect"])) < abs(np.log(unadj["effect"]))


class TestContractAndGuards:
    def test_note_disclaims_causality(self) -> None:
        """§29 + Principle 4：必须注明调整后关联不等于因果效应 + 调整清单（无隐藏模型）。"""
        result = adjusted_association(
            _confounded_clf(),
            task_type="classification",
            exposure="treatment",
            confounders=["age"],
            label_col="outcome",
        )
        assert "age" in result["note"]
        assert "关联" in result["note"] and "因果" in result["note"]

    def test_confounder_equals_exposure_raises(self) -> None:
        with pytest.raises(ValueError):
            adjusted_association(
                _confounded_clf(),
                task_type="classification",
                exposure="treatment",
                confounders=["treatment"],
                label_col="outcome",
            )

    def test_missing_column_raises(self) -> None:
        with pytest.raises(ValueError):
            adjusted_association(
                _confounded_clf(),
                task_type="classification",
                exposure="treatment",
                confounders=["no_such"],
                label_col="outcome",
            )

    def test_empty_confounders_raises(self) -> None:
        """混杂清单为空等同单因素分析 → 拒绝（避免「伪调整」报告）。"""
        with pytest.raises(ValueError):
            adjusted_association(
                _confounded_clf(),
                task_type="classification",
                exposure="treatment",
                confounders=[],
                label_col="outcome",
            )
