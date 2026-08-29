"""T6.13 对话式迭代引擎单测（tasks/phase6 T6.13）。

- 规则回退：问题中提到的真实列/模型 → 结构化重跑建议；未提到 → 只给提问指引；
- 回答只引用 facts 中的真实数值（红线8：不虚构统计量）；
- 剔除意图（去掉/剔除/移除）映射 drop_features，否则默认 add_features。
"""

from app.engines.iteration import rule_based_advice


def _facts() -> dict:
    return {
        "task_type": "classification",
        "available_columns": ["age", "bmi", "smoking", "label"],
        "available_models": ["logreg", "rf", "xgboost", "catboost"],
        "selected_models": ["logreg", "rf", "xgboost"],
        "top_model": "rf",
        "top_reason": "主指标最高（auc=0.8700±0.0100）",
    }


class TestColumnIntent:
    def test_add_covariate_question(self) -> None:
        out = rule_based_advice("如果把 bmi 当协变量会怎样？", _facts())
        assert out["suggestion"]["add_features"] == ["bmi"]
        assert out["suggestion"]["drop_features"] == []
        assert "bmi" in out["answer"]
        # 真实指标进回答（来自 facts.top_reason，非虚构）
        assert "0.8700" in out["answer"]

    def test_drop_intent(self) -> None:
        out = rule_based_advice("去掉 smoking 再跑一遍会怎样？", _facts())
        assert out["suggestion"]["drop_features"] == ["smoking"]
        assert out["suggestion"]["add_features"] == []

    def test_unknown_column_not_suggested(self) -> None:
        out = rule_based_advice("如果把 cholesterol 加进来呢？", _facts())
        assert out["suggestion"] is None or not out["suggestion"]["add_features"]
        assert "cholesterol" in out["answer"]  # 如实告知该列不在数据集中

    def test_target_column_excluded_from_features(self) -> None:
        """结局列不可作为协变量建议（facts 不含结局列，mention 也不应进建议）。"""
        facts = _facts()
        facts["available_columns"] = ["age", "bmi"]
        out = rule_based_advice("把 label 当协变量？", facts)
        assert out["suggestion"] is None or "label" not in out["suggestion"]["add_features"]


class TestModelIntent:
    def test_mentioned_model_added(self) -> None:
        out = rule_based_advice("再加上 catboost 比较一下？", _facts())
        assert out["suggestion"]["selected_models"] == ["logreg", "rf", "xgboost", "catboost"]

    def test_already_selected_model_no_change(self) -> None:
        out = rule_based_advice("rf 表现为什么最好？", _facts())
        # rf 已在选择集中 → 模型建议不变（None 表示无需调整）
        assert out["suggestion"] is None or out["suggestion"]["selected_models"] is None
        assert "rf" in out["answer"]


class TestNoIntent:
    def test_generic_question_no_suggestion(self) -> None:
        out = rule_based_advice("结果可信吗？", _facts())
        assert out["suggestion"] is None
        assert out["answer"]  # 仍有回答（指引如何提问）

    def test_answer_only_cites_real_numbers(self) -> None:
        """回答中出现的数值必须全部来自 facts（除常见阈值）。"""
        out = rule_based_advice("把 age 纳入会怎样？", _facts())
        assert "0.8700" in out["answer"]  # facts 真实值
        assert "0.95" not in out["answer"]  # 不虚构
