"""P1-01 Variable Dictionary（updateplan §11，先行测试）。

列画像扩展字典字段：unit / clinical_role / timepoint / reference_range / warnings。
参考范围只允许确定性来源（domain_knowledge 内置词典 / dataset_inferred 观测范围 /
user_defined 用户定义），禁止 LLM 凭空生成医学参考范围（§11 红线）。
"""

import numpy as np
import pandas as pd
from app.engines.validation import validate


def _clinical_df(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "patient_id": [f"P{i:04d}" for i in range(n)],
            "age": rng.normal(60, 10, n),
            "potassium": rng.normal(4.2, 0.5, n),
            "bmi": rng.normal(24, 3, n),
            "os_months": rng.exponential(30, n),
            "outcome": rng.binomial(1, 0.3, n),
        }
    )


def _profile(report, name: str) -> dict:
    return next(p for p in report.column_profiles if p["name"] == name)


class TestDictionaryFields:
    def test_all_profiles_have_dictionary_fields(self) -> None:
        report = validate(_clinical_df())
        for p in report.column_profiles:
            assert "unit" in p and "clinical_role" in p
            assert "timepoint" in p and "reference_range" in p
            assert "warnings" in p and isinstance(p["warnings"], list)

    def test_clinical_role_mapping(self) -> None:
        report = validate(_clinical_df())
        assert _profile(report, "outcome")["clinical_role"] == "outcome"
        assert _profile(report, "os_months")["clinical_role"] == "time"
        assert _profile(report, "patient_id")["clinical_role"] == "identifier"
        assert _profile(report, "age")["clinical_role"] == "baseline"
        assert _profile(report, "bmi")["clinical_role"] == "covariate"

    def test_timepoint_mapping(self) -> None:
        report = validate(_clinical_df())
        assert _profile(report, "outcome")["timepoint"] == "T1"
        assert _profile(report, "os_months")["timepoint"] == "T1+"
        assert _profile(report, "age")["timepoint"] == "T0"


class TestReferenceRange:
    def test_domain_knowledge_range_for_known_clinical_variable(self) -> None:
        """内置 RV502 词典命中（potassium）→ source=domain_knowledge 且带单位。"""
        report = validate(_clinical_df())
        rr = _profile(report, "potassium")["reference_range"]
        assert rr is not None
        assert rr["source"] == "domain_knowledge"
        assert rr["low"] == 2.5 and rr["high"] == 6.5
        assert rr["unit"] == "mmol/L"
        assert _profile(report, "potassium")["unit"] == "mmol/L"

    def test_age_uses_domain_knowledge_range(self) -> None:
        report = validate(_clinical_df())
        rr = _profile(report, "age")["reference_range"]
        assert rr is not None and rr["source"] == "domain_knowledge"
        assert rr["low"] == 0.0 and rr["high"] == 120.0

    def test_dataset_inferred_range_for_unmatched_continuous(self) -> None:
        """无临床词典命中的连续列 → 观测范围，source=dataset_inferred（非医学参考）。"""
        report = validate(_clinical_df())
        p = _profile(report, "bmi")
        rr = p["reference_range"]
        assert rr is not None and rr["source"] == "dataset_inferred"
        assert rr["low"] == p["min"] and rr["high"] == p["max"]
        assert rr["unit"] is None

    def test_categorical_column_has_no_reference_range(self) -> None:
        report = validate(_clinical_df())
        assert _profile(report, "outcome")["reference_range"] is None

    def test_source_enum_closed(self) -> None:
        """来源枚举闭合：domain_knowledge / dataset_inferred / user_defined（§11）。"""
        report = validate(_clinical_df())
        allowed = {"domain_knowledge", "dataset_inferred", "user_defined"}
        for p in report.column_profiles:
            rr = p["reference_range"]
            if rr is not None:
                assert rr["source"] in allowed


class TestWarnings:
    def test_column_issue_appears_in_warnings(self) -> None:
        """age=598 触发 RV502（critical）→ age 行 warnings 含 RV502。"""
        df = _clinical_df()
        df.loc[0, "age"] = 598.0
        report = validate(df)
        assert "RV502" in _profile(report, "age")["warnings"]

    def test_clean_column_has_empty_warnings(self) -> None:
        report = validate(_clinical_df())
        assert _profile(report, "outcome")["warnings"] == []
