"""T2.3 列类型推断 + 语义识别词典单测（docs/05 §2、docs/08 §1.2、docs/19）。

DoD：词典内列名识别率 100%；输出 semantic+confidence。
"""

import pandas as pd
import pytest
from app.engines.columns import (
    SEMANTIC_DICT,
    infer_dtype,
    recognize_semantic,
)


class TestInferDtype:
    def test_continuous_float(self) -> None:
        s = pd.Series([1.5, 2.7, 3.14, 99.9, 0.5, 7.7, 8.8, 9.9, 10.1, 11.2, 12.3])
        assert infer_dtype(s) == "continuous"

    def test_continuous_int_high_cardinality(self) -> None:
        assert infer_dtype(pd.Series(range(100))) == "continuous"

    def test_binary_is_categorical(self) -> None:
        assert infer_dtype(pd.Series([0, 1, 1, 0, 1, 0, 1, 1, 0, 1])) == "categorical"

    def test_small_int_is_categorical(self) -> None:
        assert infer_dtype(pd.Series([1, 2, 3, 1, 2, 3, 1, 2, 3, 1])) == "categorical"

    def test_datetime_dtype(self) -> None:
        s = pd.Series(pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]))
        assert infer_dtype(s) == "datetime"

    def test_datetime_strings(self) -> None:
        s = pd.Series(["2024-01-01", "2024-02-15", "2023-12-31", "2024-06-30"])
        assert infer_dtype(s) == "datetime"

    def test_mostly_numeric_strings_are_continuous(self) -> None:
        # RV301 场景：数值列混入少量非法值，仍推断为数值意图
        s = pd.Series(["1.2", "3.4", "未知", "5.6", "7.8", "9.0", "2.2", "4.4", "6.6", "8.8"])
        assert infer_dtype(s) == "continuous"

    def test_all_unique_strings_are_id(self) -> None:
        s = pd.Series([f"PAT{i:04d}" for i in range(20)])
        assert infer_dtype(s) == "id"

    def test_low_cardinality_strings_are_categorical(self) -> None:
        s = pd.Series(["男", "女", "男", "女", "男", "女", "男", "女", "男", "女"])
        assert infer_dtype(s) == "categorical"

    def test_long_strings_are_text(self) -> None:
        s = pd.Series(["这是一段非常长的自由文本备注" * 5, "另一段很长的临床病程记录" * 5])
        assert infer_dtype(s) == "text"

    def test_empty_series(self) -> None:
        assert infer_dtype(pd.Series([None, None], dtype=object)) == "text"


class TestSemanticDictCoverage:
    """DoD：词典内列名识别率 100%（精确匹配 confidence=1.0）。"""

    @pytest.mark.parametrize(
        "expected,name",
        [(sem, name) for sem, names in SEMANTIC_DICT.items() for name in names],
    )
    def test_dict_entries_recognized(self, expected: str, name: str) -> None:
        result = recognize_semantic(name, pd.Series([0, 1, 2]))
        assert result.semantic == expected
        assert result.confidence == pytest.approx(1.0)
        assert result.reason


class TestRecognizeSemantic:
    def test_token_match(self) -> None:
        result = recognize_semantic("Age (years)", pd.Series(range(10)))
        assert result.semantic == "Age"
        assert result.confidence == pytest.approx(0.9)

    def test_no_false_positive_on_substring(self) -> None:
        # "storage" 含 "age" 但不应误判为 Age
        result = recognize_semantic("storage", pd.Series(range(10)))
        assert result.semantic is None

    def test_chinese_substring_match(self) -> None:
        # "入院年龄" 非词典条目，靠中文子串命中 "年龄"
        result = recognize_semantic("入院年龄", pd.Series(range(10)))
        assert result.semantic == "Age"
        assert result.confidence >= 0.9

    def test_event_pattern_rule(self) -> None:
        # 08 §1.2 模式规则：0/1 且列名含 status → 事件列（非词典精确/token 命中）
        result = recognize_semantic("status01", pd.Series([0, 1, 1, 0, 1]))
        assert result.semantic == "Event"
        assert 0.0 < result.confidence < 1.0

    def test_binary_non_event_name_not_event(self) -> None:
        result = recognize_semantic("xyz_flag", pd.Series([0, 1, 0, 1]))
        assert result.semantic is None

    def test_unknown_column(self) -> None:
        result = recognize_semantic("xyzzy", pd.Series(["a", "b"]))
        assert result.semantic is None
        assert result.confidence == 0.0

    def test_case_insensitive(self) -> None:
        result = recognize_semantic("OS_MONTHS", pd.Series(range(10)))
        assert result.semantic == "FollowUp"
