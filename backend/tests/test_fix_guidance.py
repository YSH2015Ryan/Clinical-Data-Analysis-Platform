"""P2-3 结构化修复指引引擎测试（engines/fix_guidance.py）。

契约：每条校验 Issue 产出结构化闭环 —— 问题 → 影响 → 修法列表（含可一键执行的
quickfix 动作或手动步骤）；纯函数、确定性、可 JSON 序列化；未知规则回退默认结构。
"""

from app.engines.fix_guidance import fix_guidance_for
from app.engines.validation import Issue


def _issue(
    rule_id: str, severity: str = "warning", column: str | None = "bmi", rows: int = 10
) -> Issue:
    return Issue(rule_id, severity, "msg", column=column, affected_rows=rows)


class TestContract:
    def test_structure_keys(self) -> None:
        g = fix_guidance_for(_issue("RV201"))
        assert set(g) == {"problem", "impact", "methods"}
        assert g["problem"] and g["impact"]
        assert isinstance(g["methods"], list) and len(g["methods"]) >= 1
        for m in g["methods"]:
            assert set(m) == {"label", "description", "action", "risk"}
            if m["action"] is not None:
                assert set(m["action"]) == {"type", "column", "params"}

    def test_json_serializable(self) -> None:
        import json

        for rid in (
            "RV001",
            "RV003",
            "RV101",
            "RV201",
            "RV301",
            "RV401",
            "RV501",
            "RV502",
            "RV601",
            "RV701",
            "RV801",
            "RV802",
            "RV803",
            "RV804",
            "RV999",
        ):
            json.dumps(fix_guidance_for(_issue(rid)), ensure_ascii=False)

    def test_deterministic(self) -> None:
        assert fix_guidance_for(_issue("RV501", column="wbc")) == fix_guidance_for(
            _issue("RV501", column="wbc")
        )


class TestActionMapping:
    def test_rv201_warning_impute_first(self) -> None:
        g = fix_guidance_for(_issue("RV201", "warning", "bmi", 20))
        first = g["methods"][0]
        assert first["action"] == {
            "type": "impute_missing",
            "column": "bmi",
            "params": {"strategy": "auto"},
        }
        assert first["risk"]  # 一键动作必附风险说明

    def test_rv201_blocker_no_impute(self) -> None:
        """阻塞级（>50% 缺失）不推荐插补：首选删除列，插补不出现在修法里。"""
        g = fix_guidance_for(_issue("RV201", "blocker", "bmi", 60))
        types = [m["action"]["type"] for m in g["methods"] if m["action"]]
        assert "impute_missing" not in types
        assert types[0] == "drop_column"

    def test_rv301_to_missing(self) -> None:
        g = fix_guidance_for(_issue("RV301", "blocker", "alt", 3))
        actions = [m["action"] for m in g["methods"] if m["action"]]
        assert actions[0] == {"type": "to_missing", "column": "alt", "params": {}}

    def test_rv401_drop_duplicates(self) -> None:
        g = fix_guidance_for(_issue("RV401", "warning", None, 2))
        actions = [m["action"] for m in g["methods"] if m["action"]]
        assert actions[0]["type"] == "drop_duplicates"

    def test_rv501_and_rv804_winsorize(self) -> None:
        for rid in ("RV501", "RV804"):
            g = fix_guidance_for(_issue(rid, "warning", "crp", 4))
            actions = [m["action"] for m in g["methods"] if m["action"]]
            assert actions[0]["type"] == "winsorize_outliers"
            assert actions[0]["column"] == "crp"

    def test_rv802_drop_rows(self) -> None:
        g = fix_guidance_for(_issue("RV802", "warning", "result", 7))
        actions = [m["action"] for m in g["methods"] if m["action"]]
        assert actions[0]["type"] == "drop_rows_with_pattern"
        assert actions[0]["params"].get("pattern")

    def test_rv601_drop_column(self) -> None:
        g = fix_guidance_for(_issue("RV601", "info", "patient_name", 0))
        actions = [m["action"] for m in g["methods"] if m["action"]]
        assert actions[0]["type"] == "drop_column"

    def test_manual_only_rules_have_no_action(self) -> None:
        """不可逆/需人工判断的规则只给手动修法（action=None 的描述性修法）。"""
        for rid in ("RV001", "RV003", "RV101", "RV502", "RV801", "RV803"):
            g = fix_guidance_for(_issue(rid, "blocker"))
            assert all(m["action"] is None for m in g["methods"]), rid
            assert all(m["description"] for m in g["methods"]), rid

    def test_unknown_rule_fallback(self) -> None:
        g = fix_guidance_for(_issue("RV999", "info"))
        assert g["methods"] and all(m["action"] is None for m in g["methods"])
