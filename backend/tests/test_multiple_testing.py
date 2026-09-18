"""P1-13 多重比较校正（updateplan §30，先行测试）。

BH(FDR) 默认 / Bonferroni 可切换 / 不校正必须警告；显著性判定基于校正后 p 值。
校正数值以手算 BH/Bonferroni 为基准（非 statsmodels 自证）。
"""

import pandas as pd
import pytest
from app.engines.multiple_testing import adjust_pvalues
from app.engines.screening import subgroup_analysis, univariate_screen

from tests.test_screening import _classification_df


class TestAdjustPvalues:
    def test_bh_hand_computed(self) -> None:
        # m=3，原始顺序 [0.001, 0.02, 0.03]
        # 升序秩：0.001×3/1=0.003；0.02×3/2=0.03；0.03×3/3=0.03
        # 自大秩向小秩累积 min → 原始顺序 [0.003, 0.03, 0.03]
        assert adjust_pvalues([0.001, 0.02, 0.03], method="bh") == pytest.approx(
            [0.003, 0.03, 0.03]
        )

    def test_bonferroni_clipped_at_1(self) -> None:
        assert adjust_pvalues([0.001, 0.5], method="bonferroni") == pytest.approx([0.002, 1.0])

    def test_none_passthrough(self) -> None:
        assert adjust_pvalues([0.001, 0.5], method="none") == [0.001, 0.5]

    def test_none_values_preserved(self) -> None:
        adjusted = adjust_pvalues([0.01, None, 0.04], method="bh")
        assert adjusted[1] is None
        # None 不计入检验总数：m=2 → 0.01×2/1=0.02；0.04×2/2=0.04
        assert adjusted[0] == pytest.approx(0.02)
        assert adjusted[2] == pytest.approx(0.04)

    def test_invalid_method_raises(self) -> None:
        with pytest.raises(ValueError):
            adjust_pvalues([0.05], method="fdr_bh")  # 仅接受 bh / bonferroni / none


class TestScreenCorrection:
    def test_bh_default_rows_carry_adjusted(self) -> None:
        result = univariate_screen(
            _classification_df(), task_type="classification", label_col="outcome"
        )
        assert result["correction"] == "bh"
        assert result["n_tests"] == len(result["rows"])
        assert result["correction_warning"] is None
        for row in result["rows"]:
            assert row["p_adjusted"] is not None
            assert row["p_adjusted"] >= row["p_value"] - 1e-12
            # §30：显著性判定基于校正后 p 值
            assert row["selected"] == bool(row["p_adjusted"] < result["alpha"])

    def test_none_correction_warns_and_uses_raw(self) -> None:
        result = univariate_screen(
            _classification_df(),
            task_type="classification",
            label_col="outcome",
            correction="none",
        )
        assert result["correction_warning"]  # 选择「不校正」必须显示警告
        for row in result["rows"]:
            assert row["p_adjusted"] == row["p_value"]
            assert row["selected"] == bool(row["p_value"] < result["alpha"])

    def test_bonferroni_not_looser_than_bh(self) -> None:
        df = _classification_df()
        bonf = univariate_screen(
            df, task_type="classification", label_col="outcome", correction="bonferroni"
        )
        bh = univariate_screen(df, task_type="classification", label_col="outcome", correction="bh")
        for rb, rh in zip(bonf["rows"], bh["rows"], strict=True):
            assert rb["feature"] == rh["feature"]
            assert rb["p_adjusted"] >= rh["p_adjusted"] - 1e-12

    def test_single_test_adjusted_equals_raw(self) -> None:
        result = univariate_screen(
            _classification_df(),
            task_type="classification",
            label_col="outcome",
            features=["age"],
        )
        assert result["n_tests"] == 1
        assert result["rows"][0]["p_adjusted"] == pytest.approx(result["rows"][0]["p_value"])

    def test_invalid_correction_raises(self) -> None:
        with pytest.raises(ValueError):
            univariate_screen(
                _classification_df(),
                task_type="classification",
                label_col="outcome",
                correction="holm",
            )


class TestBaselineTableCorrection:
    """§30 覆盖基线表分层组间检验（t/Mann-Whitney/χ² 批量场景）。"""

    def _stratified_df(self) -> pd.DataFrame:
        import numpy as np

        rng = np.random.default_rng(9)
        n = 120
        return pd.DataFrame(
            {
                "group": ["A"] * (n // 2) + ["B"] * (n // 2),
                "age": rng.normal(60, 10, n),
                "bmi": rng.normal(24, 3, n),
                "sex": rng.integers(0, 2, n),
            }
        )

    def test_rows_carry_adjusted_and_table_metadata(self) -> None:
        from app.engines.reporting.baseline_table import generate_baseline_table

        result = generate_baseline_table(self._stratified_df(), stratify_by="group")
        assert result["correction"] == "bh"
        assert result["n_tests"] >= 2  # age + bmi + sex
        tested = [r for r in result["rows"] if r.get("p_value") is not None]
        assert len(tested) == result["n_tests"]
        for row in tested:
            assert row["p_adjusted"] >= row["p_value"] - 1e-12
            assert row["p_adjusted_text"]
        # §30：显著性说明须注明校正方法与检验总数
        assert "Benjamini" in result["note"] and str(result["n_tests"]) in result["note"]

    def test_no_stratify_no_correction(self) -> None:
        from app.engines.reporting.baseline_table import generate_baseline_table

        result = generate_baseline_table(self._stratified_df())
        assert result["correction"] is None
        assert result["n_tests"] == 0


class TestSubgroupCorrection:
    def test_interaction_p_adjusted_across_vars(self) -> None:
        df = _classification_df(n=300)
        df["treated"] = (df["risk_score"] > df["risk_score"].median()).astype(int)
        df["age_grp"] = pd.cut(df["age"], bins=2, labels=["低", "高"]).astype(str)
        result = subgroup_analysis(
            df,
            task_type="classification",
            exposure="treated",
            label_col="outcome",
            subgroup_vars=["sex", "age_grp"],
        )
        assert result["correction"] == "bh"
        assert result["n_tests"] == 2
        for sub in result["subgroups"]:
            if sub["interaction_p"] is not None:
                assert sub["interaction_p_adjusted"] is not None
                assert sub["interaction_p_adjusted"] >= sub["interaction_p"] - 1e-12

    def test_single_subgroup_adjusted_equals_raw(self) -> None:
        df = _classification_df(n=300)
        df["treated"] = (df["risk_score"] > df["risk_score"].median()).astype(int)
        result = subgroup_analysis(
            df,
            task_type="classification",
            exposure="treated",
            label_col="outcome",
            subgroup_vars=["sex"],
        )
        sub = result["subgroups"][0]
        if sub["interaction_p"] is not None:
            assert sub["interaction_p_adjusted"] == pytest.approx(sub["interaction_p"])
