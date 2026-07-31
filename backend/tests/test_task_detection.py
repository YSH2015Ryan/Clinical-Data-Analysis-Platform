"""T4.1 任务识别规则引擎（docs/08 §1；DoD：4 类任务各 ≥3 用例 + 失败路径）。

4 类用例：survival / classification(二分类) / classification(多分类) / regression，
各 ≥3 合成用例；识别失败 recommended_task=None（API 层映射 422，T4.2）。
"""

import numpy as np
import pandas as pd
from app.engines.task_detection import detect_task


def _df(**cols: list[object]) -> pd.DataFrame:
    return pd.DataFrame(cols)


class TestSurvival:
    def test_os_months_death(self) -> None:
        df = _df(age=[50.0, 60.0, 70.0], os_months=[12.0, 24.0, 36.0], death=[0, 1, 0])
        r = detect_task(df)
        assert r.recommended_task == "survival"
        assert r.confidence > 0.8
        assert "os_months" in r.reason
        assert r.candidates["time_col"][0].column == "os_months"
        assert r.candidates["event_col"][0].column == "death"

    def test_cjk_survival_columns(self) -> None:
        df = _df(生存时间=[10.0, 20.0, 30.0], 死亡=[0, 1, 1])
        r = detect_task(df)
        assert r.recommended_task == "survival"
        assert r.candidates["time_col"][0].column == "生存时间"
        assert r.candidates["event_col"][0].column == "死亡"

    def test_followup_days_event(self) -> None:
        df = _df(followup_days=[100.0, 200.0, 300.0], event=[1, 0, 1])
        r = detect_task(df)
        assert r.recommended_task == "survival"


class TestClassificationBinary:
    def test_death_only(self) -> None:
        df = _df(age=[50.0, 60.0, 70.0], death=[0, 1, 0])
        r = detect_task(df)
        assert r.recommended_task == "classification"
        assert r.candidates["label_col"][0].column == "death"

    def test_label_binary(self) -> None:
        df = _df(x=[1.0, 2.0, 3.0], label=[0, 1, 0])
        r = detect_task(df)
        assert r.recommended_task == "classification"

    def test_recurrence_binary(self) -> None:
        df = _df(wbc=[5.0, 6.0, 7.0], recurrence=[1, 0, 1])
        r = detect_task(df)
        assert r.recommended_task == "classification"
        assert r.candidates["label_col"][0].column == "recurrence"


class TestClassificationMulticlass:
    def test_group_three_levels(self) -> None:
        df = _df(x=[1.0, 2.0, 3.0, 4.0], group=["A", "B", "C", "A"])
        r = detect_task(df)
        assert r.recommended_task == "classification"
        assert r.candidates["label_col"][0].column == "group"

    def test_label_three_levels(self) -> None:
        df = _df(x=[1.0, 2.0, 3.0, 4.0], label=["低", "中", "高", "低"])
        r = detect_task(df)
        assert r.recommended_task == "classification"

    def test_outcome_categorical(self) -> None:
        df = _df(x=[1.0, 2.0, 3.0, 4.0], outcome=["缓解", "稳定", "进展", "缓解"])
        r = detect_task(df)
        assert r.recommended_task == "classification"


class TestRegression:
    def test_label_continuous(self) -> None:
        df = _df(x=[1.0, 2.0, 3.0, 4.0], label=[0.5, 1.5, 2.5, 3.5])
        r = detect_task(df)
        assert r.recommended_task == "regression"
        assert r.candidates["label_col"][0].column == "label"

    def test_outcome_continuous(self) -> None:
        df = _df(x=[1.0, 2.0, 3.0, 4.0], outcome=[3.1, 4.2, 5.3, 6.4])
        r = detect_task(df)
        assert r.recommended_task == "regression"

    def test_followup_without_event(self) -> None:
        df = _df(age=[50.0, 60.0, 70.0], os_months=[12.0, 24.0, 36.0])
        r = detect_task(df)
        assert r.recommended_task == "regression"
        assert r.candidates["label_col"][0].column == "os_months"


class TestFailurePath:
    def test_no_candidates_returns_none(self) -> None:
        df = _df(x1=[1.0, 2.0, 3.0], x2=[4.0, 5.0, 6.0])
        r = detect_task(df)
        assert r.recommended_task is None
        assert r.confidence == 0.0
        assert r.reason

    def test_only_id_and_text_returns_none(self) -> None:
        df = _df(
            patient_id=["P1", "P2", "P3"],
            note=["长文本" * 30, "另一段" * 30, "再一段" * 30],
        )
        r = detect_task(df)
        assert r.recommended_task is None

    def test_output_contract_shape(self) -> None:
        df = _df(os_months=[12.0, 24.0, 36.0], death=[0, 1, 0])
        r = detect_task(df)
        payload = r.to_dict()
        assert set(payload) == {
            "recommended_task",
            "confidence",
            "reason",
            "candidates",
            "user_override",
        }
        assert payload["user_override"] is None
        assert 0.0 <= payload["confidence"] <= 1.0


class TestEdgeCases:
    def test_non_binary_event_not_survival(self) -> None:
        # death 列若取值非 0/1（数据异常），不判 survival
        df = _df(os_months=[12.0, 24.0, 36.0], death=[0, 1, 2])
        r = detect_task(df)
        assert r.recommended_task != "survival"

    def test_confidence_scales_with_semantic_strength(self) -> None:
        strong = detect_task(_df(os_months=[1.0, 2.0, 3.0], death=[0, 1, 0]))
        weak = detect_task(_df(days_to_event=[1.0, 2.0, 3.0], death=[0, 1, 0]))  # 仅模式规则命中
        assert strong.recommended_task == "survival"
        assert weak.recommended_task == "survival"
        assert strong.confidence > weak.confidence

    def test_id_column_not_candidate(self) -> None:
        ids = [f"P{i}" for i in range(20)]
        df = _df(patient_id=ids, x=list(np.linspace(1, 20, 20)))
        r = detect_task(df)
        assert r.recommended_task is None  # id 列不得成为候选
