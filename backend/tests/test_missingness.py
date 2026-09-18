"""P1-11 缺失数据机制判断（updateplan §12，先行测试）。

启发式（非严格因果推断）：missing_indicator ~ 其他已观测变量 → MAR 线索；
missing_indicator ~ 结局 → Possible MNAR + 固定 WARNING；均无关联 → Likely MCAR；
缺失例数过少 → Undetermined。默认原则：不静默插补。
"""

import numpy as np
import pandas as pd
from app.engines.eda import compute_eda
from app.engines.missingness import OUTCOME_MISSINGNESS_WARNING, analyze_missingness


def _mcar_df(n: int = 400, seed: int = 1) -> pd.DataFrame:
    """缺失与任何变量/结局无关 → Likely MCAR。"""
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, n)
    lab = (x + rng.normal(0, 1, n) > 0).astype(int)
    biomarker = rng.normal(5, 1, n)
    mask = rng.uniform(0, 1, n) < 0.2  # 纯随机缺失
    biomarker[mask] = np.nan
    return pd.DataFrame({"x": x, "biomarker": biomarker, "label": lab})


def _mar_df(n: int = 600, seed: int = 2) -> pd.DataFrame:
    """缺失概率依赖已观测变量 age（与结局无关）→ Likely MAR。"""
    rng = np.random.default_rng(seed)
    age = rng.normal(60, 10, n)
    lab = (rng.normal(0, 1, n) > 0).astype(int)  # 结局与 age 无关
    bmi = rng.normal(24, 3, n)
    p_missing = 1 / (1 + np.exp(-(age - 62) / 3))  # 高龄更易缺失
    bmi[rng.uniform(0, 1, n) < p_missing] = np.nan
    return pd.DataFrame({"age": age, "bmi": bmi, "label": lab})


def _mnar_df(n: int = 600, seed: int = 3) -> pd.DataFrame:
    """缺失概率依赖结局 → Possible MNAR + 必须 WARNING。"""
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, n)
    lab = (x + rng.normal(0, 1, n) > 0).astype(int)
    troponin = rng.normal(0.1, 0.05, n)
    p_missing = np.where(lab == 1, 0.5, 0.05)  # 阳性者一半缺失
    troponin[rng.uniform(0, 1, n) < p_missing] = np.nan
    return pd.DataFrame({"x": x, "troponin": troponin, "label": lab})


class TestMechanismClassification:
    def test_mcar_when_no_association(self) -> None:
        result = analyze_missingness(_mcar_df(), outcome_cols=["label"])
        row = next(v for v in result["variables"] if v["column"] == "biomarker")
        assert row["mechanism"] == "likely_mcar"
        assert row["warning"] is None
        assert result["has_outcome_associated_missingness"] is False

    def test_mar_when_associated_with_observed(self) -> None:
        result = analyze_missingness(_mar_df(), outcome_cols=["label"])
        row = next(v for v in result["variables"] if v["column"] == "bmi")
        assert row["mechanism"] == "likely_mar"
        assert "age" in row["associated_variables"]
        assert row["warning"] is None
        # MAR → 建议 MICE / 回归插补（§12 插补策略匹配）
        assert "MICE" in row["imputation_advice"] or "多重插补" in row["imputation_advice"]

    def test_mnar_when_associated_with_outcome(self) -> None:
        result = analyze_missingness(_mnar_df(), outcome_cols=["label"])
        row = next(v for v in result["variables"] if v["column"] == "troponin")
        assert row["mechanism"] == "possible_mnar"
        assert row["outcome_association_p"] is not None
        assert row["outcome_association_p"] < result["alpha"]
        # §12 固定 WARNING（逐字）
        assert row["warning"] == OUTCOME_MISSINGNESS_WARNING.replace("{col}", "troponin")
        assert result["has_outcome_associated_missingness"] is True

    def test_undetermined_when_too_few_missing(self) -> None:
        df = _mcar_df()
        df.loc[df.index[:3], "biomarker"] = np.nan  # 仅 3 例缺失
        df.loc[df.index[3:], "biomarker"] = _mcar_df()["biomarker"].iloc[3:].fillna(5.0)
        result = analyze_missingness(df, outcome_cols=["label"])
        row = next(v for v in result["variables"] if v["column"] == "biomarker")
        assert row["mechanism"] == "undetermined"

    def test_complete_columns_excluded(self) -> None:
        result = analyze_missingness(_mcar_df(), outcome_cols=["label"])
        cols = [v["column"] for v in result["variables"]]
        assert "x" not in cols and "label" not in cols  # 无缺失列不出现

    def test_no_outcome_still_classifies_mar_mcar(self) -> None:
        result = analyze_missingness(_mar_df())
        row = next(v for v in result["variables"] if v["column"] == "bmi")
        assert row["mechanism"] == "likely_mar"  # 无结局时仍可判 MAR


class TestEdaIntegration:
    """compute_eda 自动挂接：结局列按 semantic=Event/Label 画像识别。"""

    def test_eda_payload_includes_missingness(self) -> None:
        df = _mnar_df()
        profiles = [
            {"name": "x", "inferred_type": "continuous"},
            {"name": "troponin", "inferred_type": "continuous"},
            {"name": "label", "inferred_type": "categorical", "semantic": "Label", "unique": 2},
        ]
        eda = compute_eda(df, profiles)
        assert "missingness" in eda
        row = next(v for v in eda["missingness"]["variables"] if v["column"] == "troponin")
        assert row["mechanism"] == "possible_mnar"
        assert eda["missingness"]["has_outcome_associated_missingness"] is True
