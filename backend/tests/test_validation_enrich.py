"""T6.1 校验报错可操作化：富文案 guidance + 行级 row_indices 接线(docs/05 §3、tasks/phase6 T6.1)。

DoD:
- 每个 Issue 按 rule_id 关联 validation_messages 富文案(原因+多种修法+一键操作)
- 行级规则给出受影响行号(0 基,采样式上限 20)
- to_dict 契约新增 row_indices/guidance 字段(非破坏,docs/14 §5 变更记录 2026-08-28)
"""

import pandas as pd

from app.engines.validation import parse_error_issue, validate


def _clean_df(n: int = 60) -> pd.DataFrame:
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


class TestGuidanceWiring:
    """富文案按 rule_id 接线(validation_messages.py 不再是死代码)。"""

    def test_rv201_guidance_contains_methods(self) -> None:
        df = _clean_df()
        df.loc[:39, "age"] = None  # 40/60 = 66.7% 缺失 → blocker
        issue = _rules(validate(df), "RV201")[0]
        assert issue.guidance
        assert "缺失" in issue.guidance
        assert "方法" in issue.guidance  # 富文案含多种修法

    def test_rv101_maps_to_target_missing_guidance(self) -> None:
        df = _clean_df().drop(columns=["os_months", "death"])
        issue = _rules(validate(df), "RV101")[0]
        assert "目标变量" in issue.guidance or "预测什么结果" in issue.guidance

    def test_rv701_maps_to_class_imbalance_guidance(self) -> None:
        df = _clean_df(100)
        df["death"] = 0
        df.loc[0:2, "death"] = 1  # 阳性率 3% < 5%
        issue = _rules(validate(df), "RV701")[0]
        assert "不平衡" in issue.guidance

    def test_rv401_full_dup_maps_to_duplicate_rows_guidance(self) -> None:
        df = _clean_df()
        dup = df.iloc[[5, 6]].copy()
        df = pd.concat([df, dup], ignore_index=True)
        issue = next(i for i in _rules(validate(df), "RV401") if i.column is None)
        assert "重复" in issue.guidance

    def test_rv401_id_dup_maps_to_duplicate_patients_guidance(self) -> None:
        df = _clean_df()
        df.loc[10, "patient_id"] = df.loc[5, "patient_id"]
        issue = next(i for i in _rules(validate(df), "RV401") if i.column == "patient_id")
        assert "患者" in issue.guidance

    def test_parse_error_issue_has_guidance(self) -> None:
        issue = parse_error_issue("gbk")
        assert issue.guidance
        assert "GBK" in issue.guidance

    def test_all_rule_ids_produce_non_generic_guidance(self) -> None:
        """常见规则不得回退到「请参考平台文档」兜底文案。"""
        df = _clean_df()
        df.loc[:39, "age"] = None
        df.loc[3, "patient_id"] = df.loc[2, "patient_id"]
        df = pd.concat([df, df.iloc[[7]]], ignore_index=True)
        report = validate(df)
        for issue in report.issues:
            assert "请参考平台文档" not in issue.guidance, f"{issue.rule_id} 未接线富文案"


class TestRowIndices:
    """行级规则给出受影响行号(0 基,上限 20,升序)。"""

    def test_rv201_row_indices_match_missing(self) -> None:
        df = _clean_df()
        missing_rows = [1, 7, 23, 45]
        df.loc[missing_rows, "age"] = None
        # 4/60=6.7% 低于 warn 阈值,需更多缺失触发
        df.loc[range(10, 30), "age"] = None
        missing_rows = sorted(set(missing_rows) | set(range(10, 30)))
        issue = _rules(validate(df), "RV201")[0]
        assert issue.row_indices == missing_rows[:20]

    def test_rv301_row_indices_match_illegal(self) -> None:
        df = _clean_df()
        df["wbc"] = ["5.5"] * 60
        df.loc[[4, 9], "wbc"] = "未测"
        issue = _rules(validate(df), "RV301")[0]
        assert issue.row_indices == [4, 9]

    def test_rv401_full_dup_row_indices(self) -> None:
        df = _clean_df()
        df = pd.concat([df, df.iloc[[3, 11]]], ignore_index=True)
        issue = next(i for i in _rules(validate(df), "RV401") if i.column is None)
        assert issue.row_indices == [60, 61]

    def test_rv502_row_indices_out_of_range(self) -> None:
        df = _clean_df()
        df.loc[8, "age"] = 250  # 超出 0–120
        df.loc[9, "age"] = -5
        issue = _rules(validate(df), "RV502")[0]
        assert issue.row_indices == [8, 9]

    def test_row_indices_capped_at_20(self) -> None:
        df = _clean_df(100)
        df.loc[range(0, 60), "age"] = None  # 60% 缺失
        issue = _rules(validate(df), "RV201")[0]
        assert len(issue.row_indices) == 20
        assert issue.row_indices == sorted(issue.row_indices)

    def test_non_row_rule_has_no_indices(self) -> None:
        report = validate(_clean_df().drop(columns=["os_months", "death"]))
        issue = _rules(report, "RV101")[0]
        assert issue.row_indices is None


class TestContractDict:
    def test_to_dict_contains_new_fields(self) -> None:
        df = _clean_df()
        df.loc[range(20), "age"] = None
        d = _rules(validate(df), "RV201")[0].to_dict()
        assert "row_indices" in d
        assert "guidance" in d
        assert isinstance(d["guidance"], str) and d["guidance"]
