"""T6.2 任务识别偏置修正(docs/08 §1、tasks/phase6 T6.2)。

问题:任何无语义的 0/1 列以 0.5 置信度抢在回归前面 → 含标志列的数据集
被误判为分类,客户反馈「很少推荐回归」。

修正规则:
1. 泛猜(无语义、纯模式规则,conf<0.6)不得压过有语义支撑的回归候选(conf≥0.6);
2. 无语义 0/1 列仍保留在 candidates 中供用户改选;
3. detect_task 与 detect_task_from_profile 判定逻辑保持完全等价。
"""

import pandas as pd
from app.engines.task_detection import detect_task, detect_task_from_profile


def _profile_of(df: pd.DataFrame) -> list[dict]:
    """从 df 构造与验证阶段同构的 column_profile(from_profile 等价性测试用)。"""
    from app.engines.columns import infer_dtype, recognize_semantic

    profiles = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        sem = recognize_semantic(col, s)
        s_num = pd.to_numeric(s, errors="coerce")
        dtype = infer_dtype(s)
        p: dict = {
            "name": col,
            "inferred_type": dtype,
            "semantic": sem.semantic,
            "semantic_confidence": sem.confidence,
            "missing_rate": float(s.isna().sum() / n) if n else 0.0,
            "unique": int(s.nunique()),
        }
        if dtype == "continuous":
            non_null = s_num.dropna()
            if len(non_null):
                p["min"] = float(non_null.min())
                p["max"] = float(non_null.max())
        profiles.append(p)
    return profiles


class TestGenericBinaryMustNotBeatSemanticRegression:
    """核心场景:连续结局(有语义) + 无语义 0/1 标志列 → 应推荐回归。"""

    def test_label_continuous_plus_flag(self) -> None:
        df = pd.DataFrame({"flag": [0, 1, 0, 1], "label": [0.5, 1.5, 2.5, 3.5]})
        r = detect_task(df)
        assert r.recommended_task == "regression"
        assert "label" in r.reason
        # 0/1 标志列保留在候选中,用户可改选
        assert any(c.column == "flag" for c in r.candidates["label_col"])

    def test_followup_regression_plus_flag(self) -> None:
        df = pd.DataFrame({"flag": [0, 1, 0], "os_months": [12.0, 24.0, 36.0]})
        r = detect_task(df)
        assert r.recommended_task == "regression"
        assert "os_months" in r.reason

    def test_generic_multiclass_plus_semantic_regression(self) -> None:
        df = pd.DataFrame({"grp": ["A", "B", "C", "A"], "label": [0.5, 1.5, 2.5, 3.5]})
        r = detect_task(df)
        assert r.recommended_task == "regression"

    def test_reason_notes_flag_column(self) -> None:
        df = pd.DataFrame({"flag": [0, 1, 0, 1], "label": [0.5, 1.5, 2.5, 3.5]})
        r = detect_task(df)
        assert "flag" in r.reason  # 理由中说明 0/1 列被降级为候选


class TestUnchangedBehavior:
    """不应受影响的场景(回归守卫不触发)。"""

    def test_semantic_binary_still_classification(self) -> None:
        # death 有 Event 语义(≥0.85),不是泛猜 → 维持分类
        df = pd.DataFrame({"age": [50.0, 60.0, 70.0], "death": [0, 1, 0]})
        assert detect_task(df).recommended_task == "classification"

    def test_generic_binary_alone_still_classification(self) -> None:
        # 只有无语义 0/1 列、无回归候选 → 维持分类(用户确认即可)
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "flag": [0, 1, 0]})
        r = detect_task(df)
        assert r.recommended_task == "classification"

    def test_survival_untouched(self) -> None:
        df = pd.DataFrame({"os_months": [12.0, 24.0, 36.0], "death": [0, 1, 0], "flag": [1, 0, 1]})
        assert detect_task(df).recommended_task == "survival"


class TestProfileParity:
    """detect_task_from_profile 与 detect_task 判定必须一致(docs/08 §1)。"""

    def test_profile_matches_df_detection_regression(self) -> None:
        df = pd.DataFrame({"flag": [0, 1, 0, 1], "label": [0.5, 1.5, 2.5, 3.5]})
        assert detect_task_from_profile(_profile_of(df)).recommended_task == "regression"

    def test_profile_matches_df_detection_classification(self) -> None:
        df = pd.DataFrame({"age": [50.0, 60.0, 70.0], "death": [0, 1, 0]})
        assert detect_task_from_profile(_profile_of(df)).recommended_task == "classification"

    def test_profile_matches_df_detection_survival(self) -> None:
        df = pd.DataFrame({"os_months": [12.0, 24.0, 36.0], "death": [0, 1, 0]})
        assert detect_task_from_profile(_profile_of(df)).recommended_task == "survival"

    def test_profile_generic_binary_alone(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "flag": [0, 1, 0]})
        assert detect_task_from_profile(_profile_of(df)).recommended_task == "classification"
