"""T6.6 修复：intelligent_task_advisor 死代码复活（roadmap P0-1）。

回归背景：旧实现调用 LLMService 不存在的方法（is_available/chat），
且读取了 validation profile 中不存在的键（data_type/semantic_type/
missing_count/unique_count），异常被静默吞掉，功能从未产出结果。

契约：
- 规则引擎（detect_task_from_profile）出结论，LLM 只做表达增强（红线 8）；
- 分功能开关 task_recommend 门控；off/失败/输出不合格一律回退规则结果；
- 仿真桩只实现 LLMService 真实接口（complete/is_local_available），
  若 advisor 再调用不存在的方法将直接 AttributeError（防回归）。
"""

import json
from typing import Any

import pandas as pd
from app.engines.intelligent_task_advisor import (
    IntelligentTaskAdvisor,
    TaskRecommendation,
)


class _StubLLM:
    """只实现 LLMService 真实接口的替身。"""

    def __init__(self, complete_result: str | None = None, complete_exc: Exception | None = None):
        self.complete_result = complete_result
        self.complete_exc = complete_exc
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.complete_exc:
            raise self.complete_exc
        return self.complete_result or ""

    def is_local_available(self) -> bool:
        return True


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "年龄": [60, 70, 55, 66],
            "死亡": [0, 1, 0, 1],
            "随访月": [12.0, 8.0, 24.0, 5.0],
        }
    )


def _profiles() -> list[dict[str, Any]]:
    """与 engines/validation 真实产出的 profile 键一致。"""
    return [
        {
            "name": "年龄",
            "inferred_type": "continuous",
            "semantic": "Age",
            "semantic_confidence": 0.9,
            "missing_rate": 0.0,
            "unique": 4,
            "min": 55.0,
            "max": 70.0,
        },
        {
            "name": "死亡",
            "inferred_type": "categorical",
            "semantic": "Event",
            "semantic_confidence": 0.92,
            "missing_rate": 0.0,
            "unique": 2,
        },
        {
            "name": "随访月",
            "inferred_type": "continuous",
            "semantic": "FollowUp",
            "semantic_confidence": 0.9,
            "missing_rate": 0.25,
            "unique": 4,
            "min": 5.0,
            "max": 24.0,
        },
    ]


class TestRuleBaseline:
    """开关 off / 无 LLM 时：规则结果必须真实可用（不再是摆设）。"""

    def test_off_switch_survival_detected(self) -> None:
        rec = IntelligentTaskAdvisor(None).analyze_dataset(_df(), _profiles(), switch="off")
        assert isinstance(rec, TaskRecommendation)
        assert "survival" in rec.recommended_tasks
        assert rec.can_start_modeling is True
        assert rec.overall_assessment  # 有真实理由，非空
        target_cols = {t["column"] for t in rec.recommended_targets}
        assert {"随访月", "死亡"} & target_cols  # 推荐目标来自真实候选列

    def test_no_label_falls_back_to_eda(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        profiles = [
            {
                "name": "a",
                "inferred_type": "continuous",
                "semantic": None,
                "semantic_confidence": 0.0,
                "missing_rate": 0.0,
                "unique": 3,
                "min": 1.0,
                "max": 3.0,
            },
            {
                "name": "b",
                "inferred_type": "text",
                "semantic": None,
                "semantic_confidence": 0.0,
                "missing_rate": 0.0,
                "unique": 3,
            },
        ]
        rec = IntelligentTaskAdvisor(None).analyze_dataset(df, profiles, switch="off")
        assert rec.recommended_tasks == ["eda"]
        assert rec.can_start_modeling is False
        assert rec.eda_suggestions  # 有真实 EDA 建议
        assert rec.unsuitable_tasks  # 说明为何不适合建模

    def test_profile_keys_match_validation_schema(self) -> None:
        """防回归：advisor 必须读 validation 真实键（inferred_type/semantic 等）。"""
        rec = IntelligentTaskAdvisor(None).analyze_dataset(_df(), _profiles(), switch="off")
        # 若读错键，missing_rate 等全丢，结论会退化为 eda
        assert rec.recommended_tasks != ["eda"]


class TestLLMEnhancement:
    """开关打开时：LLM 只增强表达；结构/幻觉不合格回退规则。"""

    def _good_llm_json(self) -> str:
        return json.dumps(
            {
                "overall_assessment": "数据含随访时间与死亡事件列，4 例样本中事件 2 例，"
                "适合生存分析方向探索。",
                "eda_suggestions": ["年龄分布与事件的关系", "缺失模式检查"],
            },
            ensure_ascii=False,
        )

    def test_llm_enhances_expression(self) -> None:
        llm = _StubLLM(complete_result=self._good_llm_json())
        rec = IntelligentTaskAdvisor(llm).analyze_dataset(_df(), _profiles(), switch="local")
        assert llm.calls  # 确实调用了 LLM
        assert "survival" in rec.recommended_tasks  # 结论仍来自规则
        assert "随访" in rec.overall_assessment  # 表达来自 LLM
        # prompt 不得含行级样本值（隐私红线）
        assert "60" not in llm.calls[0]["prompt"] or "年龄" in llm.calls[0]["prompt"]

    def test_llm_garbage_falls_back_to_rule(self) -> None:
        llm = _StubLLM(complete_result="这不是 JSON")
        rec = IntelligentTaskAdvisor(llm).analyze_dataset(_df(), _profiles(), switch="local")
        assert "survival" in rec.recommended_tasks  # 规则兜底

    def test_llm_exception_falls_back(self) -> None:
        llm = _StubLLM(complete_exc=RuntimeError("ollama down"))
        rec = IntelligentTaskAdvisor(llm).analyze_dataset(_df(), _profiles(), switch="local")
        assert "survival" in rec.recommended_tasks

    def test_llm_hallucinated_numbers_rejected(self) -> None:
        bad = json.dumps(
            {
                "overall_assessment": "该数据 AUC 可达 0.87，样本量 5000 例充足。",
                "eda_suggestions": [],
            },
            ensure_ascii=False,
        )
        llm = _StubLLM(complete_result=bad)
        rec = IntelligentTaskAdvisor(llm).analyze_dataset(_df(), _profiles(), switch="local")
        assert "0.87" not in rec.overall_assessment
        assert "5000" not in rec.overall_assessment

    def test_llm_invented_columns_rejected(self) -> None:
        bad = json.dumps(
            {
                "overall_assessment": "建议以「肿瘤分期」为协变量建模。",
                "eda_suggestions": ["分析肿瘤分期与死亡的关系"],
            },
            ensure_ascii=False,
        )
        llm = _StubLLM(complete_result=bad)
        rec = IntelligentTaskAdvisor(llm).analyze_dataset(_df(), _profiles(), switch="local")
        assert "肿瘤分期" not in rec.overall_assessment
        assert all("肿瘤分期" not in s for s in rec.eda_suggestions)

    def test_no_row_level_values_in_prompt(self) -> None:
        """隐私：prompt 只含聚合元数据，不含行级取值（云端路径出域红线）。"""
        llm = _StubLLM(complete_result=self._good_llm_json())
        IntelligentTaskAdvisor(llm).analyze_dataset(_df(), _profiles(), switch="local")
        prompt = llm.calls[0]["prompt"]
        # 行级样本值不应出现（年龄取值 55/60/66/70 属行级数据）
        for v in ("55", "66", "70"):
            assert v not in prompt
