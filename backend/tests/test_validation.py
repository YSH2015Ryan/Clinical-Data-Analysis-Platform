"""T2.4 校验规则引擎单测：13 规则正反例 + 报告 JSON 契约（docs/05 §3/§4、docs/14）。"""

import pandas as pd
from app.engines.validation import (
    parse_error_issue,
    validate,
)


def _clean_df(n: int = 100) -> pd.DataFrame:
    """无病基线：含 Age/Gender/FollowUp/Event，无缺失/重复/异常。"""
    return pd.DataFrame(
        {
            "patient_id": [f"P{i:03d}" for i in range(n)],
            "age": [40 + i % 40 for i in range(n)],
            "gender": (["男", "女"] * (n // 2 + 1))[:n],
            "os_months": [12.0 + i % 36 for i in range(n)],
            "death": [i % 2 for i in range(n)],
        }
    )


def _rules(report, rule_id: str):
    return [i for i in report.issues if i.rule_id == rule_id]


class TestRV001ParseFailure:
    def test_positive(self) -> None:
        issue = parse_error_issue("gbk")
        assert issue.rule_id == "RV001"
        assert issue.severity == "blocker"
        assert "GBK" in issue.suggestion


class TestRV002Empty:
    def test_positive(self) -> None:
        report = validate(pd.DataFrame({"a": []}))
        assert _rules(report, "RV002")[0].severity == "blocker"
        assert report.status == "FAILED"

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV002") == []


class TestRV003DuplicateColumns:
    def test_positive(self) -> None:
        report = validate(_clean_df(), raw_columns=["age", "age", "death"])
        issue = _rules(report, "RV003")[0]
        assert issue.severity == "blocker"
        assert "age" in issue.message

    def test_negative(self) -> None:
        report = validate(_clean_df(), raw_columns=list(_clean_df().columns))
        assert _rules(report, "RV003") == []


class TestRV101RequiredFieldMissing:
    def test_positive(self) -> None:
        df = _clean_df().drop(columns=["os_months", "death"])
        issue = _rules(validate(df), "RV101")[0]
        assert issue.severity == "blocker"
        assert "结局" in issue.message

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV101") == []

    def test_label_alone_satisfies(self) -> None:
        df = _clean_df().drop(columns=["os_months"]).rename(columns={"death": "label"})
        assert _rules(validate(df), "RV101") == []


class TestRV102RecommendedFieldMissing:
    def test_missing_age(self) -> None:
        df = _clean_df().drop(columns=["age"])
        issues = _rules(validate(df), "RV102")
        assert any("Age" in i.message for i in issues)

    def test_missing_gender(self) -> None:
        df = _clean_df().drop(columns=["gender"])
        issues = _rules(validate(df), "RV102")
        assert any("Gender" in i.message for i in issues)

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV102") == []


class TestRV201MissingRate:
    def test_blocker_over_50(self) -> None:
        df = _clean_df()
        df.loc[df.index[:60], "age"] = None
        issue = _rules(validate(df), "RV201")[0]
        assert issue.severity == "blocker"
        assert issue.affected_rows == 60

    def test_warning_over_20(self) -> None:
        df = _clean_df()
        df.loc[df.index[:30], "gender"] = None
        issue = _rules(validate(df), "RV201")[0]
        assert issue.severity == "warning"

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV201") == []


class TestRV301IllegalNumeric:
    def test_positive(self) -> None:
        df = _clean_df()
        df["alt"] = ["10", "20", "未知", "30", "40", "50", "60", "70", "80", "90"] * 10
        issue = _rules(validate(df), "RV301")[0]
        assert issue.severity == "blocker"
        assert issue.column == "alt"
        assert issue.affected_rows == 10

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV301") == []


class TestRV302DateFormatMixed:
    def test_positive(self) -> None:
        df = _clean_df()
        df["visit_date"] = ["2024-01-01", "2024/01/02"] * 50
        issue = _rules(validate(df), "RV302")[0]
        assert issue.severity == "warning"

    def test_negative_single_format(self) -> None:
        df = _clean_df()
        df["visit_date"] = ["2024-01-01", "2024-02-01"] * 50
        assert _rules(validate(df), "RV302") == []


class TestRV401Duplicates:
    def test_full_row_duplicates(self) -> None:
        df = _clean_df(10)
        df = pd.concat([df, df.iloc[:5]], ignore_index=True)
        issue = _rules(validate(df), "RV401")[0]
        assert issue.severity == "warning"
        assert issue.affected_rows == 5

    def test_id_column_duplicates(self) -> None:
        df = _clean_df()
        df.loc[df.index[1], "patient_id"] = "P000"
        issues = _rules(validate(df), "RV401")
        assert any(i.column == "patient_id" for i in issues)

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV401") == []


class TestRV501Outliers:
    def test_positive(self) -> None:
        df = _clean_df(101)
        df["biomarker"] = [float(i) for i in range(100)] + [10000.0]
        issue = _rules(validate(df), "RV501")[0]
        assert issue.severity == "warning"
        assert issue.column == "biomarker"

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV501") == []


class TestRV502ClinicalRange:
    def test_potassium_out_of_range(self) -> None:
        df = _clean_df()
        # 取值需 >10 个唯一值才推断为连续列（RV502 只作用于连续列）
        df["血钾"] = [3.5 + (i % 20) * 0.1 for i in range(99)] + [0.2]
        issue = _rules(validate(df), "RV502")[0]
        assert issue.severity == "warning"
        assert "血钾" in issue.message

    def test_age_out_of_range(self) -> None:
        df = _clean_df()
        df.loc[df.index[0], "age"] = 150
        issues = _rules(validate(df), "RV502")
        assert any(i.column == "age" for i in issues)

    def test_negative(self) -> None:
        df = _clean_df()
        df["血钾"] = [3.5 + (i % 20) * 0.1 for i in range(100)]
        assert _rules(validate(df), "RV502") == []


class TestRV601HighCardinality:
    def test_positive(self) -> None:
        df = _clean_df(200)
        df["hobby"] = [f"C{i % 120:03d}" for i in range(200)]
        issue = _rules(validate(df), "RV601")[0]
        assert issue.severity == "info"
        assert issue.column == "hobby"

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV601") == []


class TestRV701LabelImbalance:
    def test_positive(self) -> None:
        df = _clean_df()
        df["death"] = [1] + [0] * 99
        issue = _rules(validate(df), "RV701")[0]
        assert issue.severity == "warning"
        assert "阳性率" in issue.message

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV701") == []


class TestReportContract:
    """报告 JSON 符合 docs/14 QualityReport 契约。"""

    def test_clean_passed(self) -> None:
        report = validate(_clean_df())
        assert report.status == "PASSED"
        assert report.blockers == 0

    def test_warning_status(self) -> None:
        df = _clean_df()
        df.loc[df.index[:30], "gender"] = None
        assert validate(df).status == "PASSED_WITH_WARNINGS"

    def test_blocker_status(self) -> None:
        df = _clean_df().drop(columns=["death", "os_months"])
        assert validate(df).status == "FAILED"

    def test_json_shape(self) -> None:
        d = validate(_clean_df()).to_dict()
        assert set(d) >= {"status", "blockers", "warnings", "issues", "column_profiles", "summary"}
        assert d["summary"]["rows"] == 100
        for issue in d["issues"]:
            assert set(issue) >= {"rule_id", "severity", "column", "message", "suggestion"}
        for col in d["column_profiles"]:
            assert set(col) >= {"name", "inferred_type", "semantic", "missing_rate", "unique"}
        import json

        json.dumps(d)  # 可序列化

    def test_column_profiles_semantics(self) -> None:
        d = validate(_clean_df()).to_dict()
        by_name = {c["name"]: c for c in d["column_profiles"]}
        assert by_name["age"]["semantic"] == "Age"
        assert by_name["age"]["inferred_type"] == "continuous"
        assert by_name["death"]["semantic"] == "Event"
        assert by_name["os_months"]["semantic"] == "FollowUp"
        assert by_name["patient_id"]["inferred_type"] == "id"
