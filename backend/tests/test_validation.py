"""T2.4 校验规则引擎单测：13 规则正反例 + 报告 JSON 契约（docs/05 §3/§4、docs/14）。"""

import pandas as pd
from app.engines.validation import (
    ValidationConfig,
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
    """T6.6 起 RV101 降级为 warning：支持无结局列数据进入探索性分析（EDA），
    建模目标列由分析创建时的硬校验把关（services/analysis.py）。"""

    def test_positive(self) -> None:
        df = _clean_df().drop(columns=["os_months", "death"])
        issue = _rules(validate(df), "RV101")[0]
        assert issue.severity == "warning"
        assert "预测目标" in issue.message

    def test_message_human_readable(self) -> None:
        """P0-3：文案面向非技术用户（docs/05 §3，2026-08-03 修订）。"""
        df = _clean_df().drop(columns=["os_months", "death"])
        issue = _rules(validate(df), "RV101")[0]
        assert "预测目标" in issue.message
        assert "目标变量" in issue.suggestion  # 指引补充或指定目标列

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

    def test_prepared_output_downgrades_blocker(self) -> None:
        """数据准备产物模式（docs/05 §8.5）：稀疏宽表 RV201 阻塞降级为警告。"""
        df = _clean_df()
        df.loc[df.index[:60], "age"] = None
        rep = validate(df, config=ValidationConfig(prepared_output=True))
        issue = _rules(rep, "RV201")[0]
        assert issue.severity == "warning"
        assert rep.blockers == 0


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
        # P0-04（updateplan §15-16）：临床不合理范围升为 critical 档
        assert issue.severity == "critical"
        assert "血钾" in issue.message

    def test_critical_counted_but_not_failed(self) -> None:
        """critical 计入报告但不等同于 blocker：status 仍为 PASSED_WITH_WARNINGS。"""
        df = _clean_df()
        df.loc[df.index[0], "age"] = 598  # updateplan §3.4 实据场景
        rep = validate(df)
        assert rep.criticals >= 1
        assert rep.blockers == 0
        assert rep.status == "PASSED_WITH_WARNINGS"
        assert rep.to_dict()["criticals"] == rep.criticals

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


class TestRV801LongTable:
    """P0-2（docs/05 §3 RV801）：检验名称+结果 列组合 → 长表结构警告。"""

    def _long_df(self, n: int = 60) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "患者ID": [f"P{i % 10:03d}" for i in range(n)],
                "检验名称": (["白细胞计数", "葡萄糖"] * (n // 2 + 1))[:n],
                "结果": [f"{5.0 + i % 5}" for i in range(n)],
            }
        )

    def test_positive(self) -> None:
        issue = _rules(validate(self._long_df()), "RV801")[0]
        assert issue.severity == "warning"
        assert "长表" in issue.message

    def test_negative_wide_table(self) -> None:
        assert _rules(validate(_clean_df()), "RV801") == []


class TestRV802Susceptibility:
    """P0-2（docs/05 §3 RV802）：判定列含 敏感/耐药/中介 → 疑似药敏警告。"""

    def test_positive(self) -> None:
        n = 60
        df = pd.DataFrame(
            {
                "患者ID": [f"P{i % 10:03d}" for i in range(n)],
                "检验名称": (["万古霉素", "白细胞计数"] * (n // 2 + 1))[:n],
                "结果": ["", "5.0"] * (n // 2),
                "异常": (["敏感（S）", "耐药（R）", "正常（N）"] * (n // 3 + 1))[:n],
            }
        )
        issue = _rules(validate(df), "RV802")[0]
        assert issue.severity == "warning"
        assert "药敏" in issue.message
        assert issue.affected_rows is not None and issue.affected_rows >= 5

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV802") == []


class TestRV803MultiUnit:
    """P0-2（docs/05 §3 RV803）：长表中同一检验项目多种单位。"""

    def test_positive(self) -> None:
        n = 60
        df = pd.DataFrame(
            {
                "患者ID": [f"P{i % 10:03d}" for i in range(n)],
                "检验名称": ["白细胞计数"] * n,
                "结果": ["5.0"] * n,
                "化验单位": (["10^9/L", "10^12/L"] * (n // 2 + 1))[:n],
            }
        )
        issue = _rules(validate(df), "RV803")[0]
        assert issue.severity == "warning"
        assert "白细胞计数" in issue.detail

    def test_negative_single_unit(self) -> None:
        n = 60
        df = pd.DataFrame(
            {
                "患者ID": [f"P{i % 10:03d}" for i in range(n)],
                "检验名称": ["白细胞计数"] * n,
                "结果": ["5.0"] * n,
                "化验单位": ["10^9/L"] * n,
            }
        )
        assert _rules(validate(df), "RV803") == []


class TestRV804ExtremeValue:
    """P0-2（docs/05 §3 RV804）：数值列极端值（默认阈值 1e6）。"""

    def test_positive(self) -> None:
        df = _clean_df(101)
        # 需 >10 个唯一值才会推断为连续列（RV804 只作用于连续列）
        df["norm_value"] = [0.5 + i * 0.01 for i in range(100)] + [55_805_580.0]
        issue = _rules(validate(df), "RV804")[0]
        assert issue.severity == "warning"
        assert issue.column == "norm_value"

    def test_negative(self) -> None:
        assert _rules(validate(_clean_df()), "RV804") == []


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
        # 真正的阻塞级问题（重复列名 RV003）→ FAILED；
        # 缺结局列（RV101）自 T6.6 起降级为 warning，不再单独导致 FAILED
        df = _clean_df()
        df.columns = ["age", "age", *df.columns[2:]]
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
