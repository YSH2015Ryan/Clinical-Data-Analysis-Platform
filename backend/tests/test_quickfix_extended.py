"""
Quick Fix 引擎测试（扩展版本）

测试新增的 6 个 Quick Fix 动作
"""

import numpy as np
import pandas as pd
import pytest
from app.engines.quickfix import (
    QuickFixAction,
    apply_actions,
)


class TestRenameColumn:
    """测试 rename_column 动作"""

    def test_rename_column_success(self):
        """测试成功重命名列"""
        df = pd.DataFrame({"血压": [120, 130, 140], "心率": [70, 80, 90]})

        action = QuickFixAction(type="rename_column", column="血压", params={"new_name": "收缩压"})

        result, log = apply_actions(df, [action])

        assert "收缩压" in result.columns
        assert "血压" not in result.columns
        assert log[0]["new_name"] == "收缩压"
        assert log[0]["affected_rows"] == 0

    def test_rename_column_duplicate_name(self):
        """测试重命名为已存在的列名"""
        df = pd.DataFrame({"血压": [120, 130, 140], "心率": [70, 80, 90]})

        action = QuickFixAction(type="rename_column", column="血压", params={"new_name": "心率"})

        with pytest.raises(ValueError, match="已存在"):
            apply_actions(df, [action])

    def test_rename_column_missing_param(self):
        """测试缺少 new_name 参数"""
        df = pd.DataFrame({"血压": [120, 130, 140]})

        action = QuickFixAction(type="rename_column", column="血压", params={})

        with pytest.raises(ValueError, match="new_name"):
            apply_actions(df, [action])


class TestPivotLongToWide:
    """测试 pivot_long_to_wide 动作"""

    def test_pivot_basic(self):
        """测试基本长表转宽表"""
        df = pd.DataFrame(
            {
                "patient_id": ["P001", "P001", "P002", "P002"],
                "test_name": ["血钾", "血钠", "血钾", "血钠"],
                "test_value": [3.5, 140, 4.2, 138],
            }
        )

        action = QuickFixAction(
            type="pivot_long_to_wide",
            column=None,
            params={
                "id_column": "patient_id",
                "item_column": "test_name",
                "value_column": "test_value",
            },
        )

        result, log = apply_actions(df, [action])

        assert len(result) == 2
        assert "blood_potassium" in result.columns or "血钾" in result.columns
        assert result.loc[result["patient_id"] == "P001", "血钾"].iloc[0] == 3.5
        assert log[0]["affected_rows"] == 4
        assert log[0]["result_rows"] == 2

    def test_pivot_with_duplicates(self):
        """测试包含重复值的长表（取平均）"""
        df = pd.DataFrame(
            {
                "patient_id": ["P001", "P001", "P001"],
                "test_name": ["血钾", "血钾", "血钠"],
                "test_value": [3.5, 3.7, 140],
            }
        )

        action = QuickFixAction(
            type="pivot_long_to_wide",
            column=None,
            params={
                "id_column": "patient_id",
                "item_column": "test_name",
                "value_column": "test_value",
            },
        )

        result, _log = apply_actions(df, [action])

        assert len(result) == 1
        # 血钾应该是 (3.5 + 3.7) / 2 = 3.6
        assert abs(result.loc[0, "血钾"] - 3.6) < 0.01

    def test_pivot_missing_params(self):
        """测试缺少必需参数"""
        df = pd.DataFrame({"a": [1], "b": [2]})

        action = QuickFixAction(type="pivot_long_to_wide", column=None, params={"id_column": "a"})

        with pytest.raises(ValueError, match="id_column, item_column, value_column"):
            apply_actions(df, [action])


class TestWinsorizeOutliers:
    """测试 winsorize_outliers 动作"""

    def test_winsorize_basic(self):
        """测试基本异常值截尾"""
        df = pd.DataFrame({"blood_pressure": [120, 130, 140, 150, 160, 200, 50]})

        action = QuickFixAction(
            type="winsorize_outliers",
            column="blood_pressure",
            params={"lower_percentile": 0.1, "upper_percentile": 0.9},
        )

        result, log = apply_actions(df, [action])

        # 极端值应该被截尾
        assert result["blood_pressure"].max() <= 180  # 接近 90th percentile
        assert result["blood_pressure"].min() >= 100  # 接近 10th percentile
        assert log[0]["affected_rows"] > 0

    def test_winsorize_no_outliers(self):
        """测试没有异常值的情况"""
        df = pd.DataFrame({"age": [20, 25, 30, 35, 40]})

        action = QuickFixAction(type="winsorize_outliers", column="age", params={})

        result, _log = apply_actions(df, [action])

        # 应该没有变化
        pd.testing.assert_series_equal(result["age"], df["age"], check_dtype=False)

    def test_winsorize_non_numeric(self):
        """测试非数值列"""
        df = pd.DataFrame({"category": ["A", "B", "C"]})

        action = QuickFixAction(type="winsorize_outliers", column="category", params={})

        with pytest.raises(ValueError, match="不是数值类型"):
            apply_actions(df, [action])


class TestImputeMissing:
    """测试 impute_missing 动作"""

    def test_impute_median(self):
        """测试中位数插补"""
        df = pd.DataFrame({"age": [20, 30, np.nan, 40, 50]})

        action = QuickFixAction(type="impute_missing", column="age", params={"strategy": "median"})

        result, log = apply_actions(df, [action])

        assert result["age"].isna().sum() == 0
        assert result["age"].iloc[2] == 35.0  # median of [20, 30, 40, 50]
        assert log[0]["affected_rows"] == 1
        assert log[0]["fill_value"] == 35.0

    def test_impute_mean(self):
        """测试均值插补"""
        df = pd.DataFrame({"score": [80, 90, np.nan, 100]})

        action = QuickFixAction(type="impute_missing", column="score", params={"strategy": "mean"})

        result, _log = apply_actions(df, [action])

        assert result["score"].isna().sum() == 0
        assert result["score"].iloc[2] == 90.0  # mean of [80, 90, 100]

    def test_impute_mode(self):
        """测试众数插补"""
        df = pd.DataFrame({"category": ["A", "B", "A", None, "A"]})

        action = QuickFixAction(
            type="impute_missing", column="category", params={"strategy": "mode"}
        )

        result, _log = apply_actions(df, [action])

        assert result["category"].isna().sum() == 0
        assert result["category"].iloc[3] == "A"  # mode

    def test_impute_constant(self):
        """测试常数插补"""
        df = pd.DataFrame({"status": ["active", None, "inactive"]})

        action = QuickFixAction(
            type="impute_missing",
            column="status",
            params={"strategy": "constant", "fill_value": "unknown"},
        )

        result, _log = apply_actions(df, [action])

        assert result["status"].iloc[1] == "unknown"

    def test_impute_auto_numeric(self):
        """测试自动选择策略（数值）"""
        df = pd.DataFrame({"value": [1, 2, np.nan, 4]})

        action = QuickFixAction(type="impute_missing", column="value", params={"strategy": "auto"})

        result, log = apply_actions(df, [action])

        # 应该使用 median
        assert result["value"].iloc[2] == 2.0
        assert log[0]["strategy"] == "median"


class TestDropRowsWithPattern:
    """测试 drop_rows_with_pattern 动作"""

    def test_drop_pattern_basic(self):
        """测试基本模式匹配删除"""
        df = pd.DataFrame({"result": ["敏感", "耐药", "阴性", "中介", "阳性"]})

        action = QuickFixAction(
            type="drop_rows_with_pattern", column="result", params={"pattern": "敏感|耐药|中介"}
        )

        result, log = apply_actions(df, [action])

        assert len(result) == 2
        assert "敏感" not in result["result"].values
        assert "耐药" not in result["result"].values
        assert log[0]["affected_rows"] == 3

    def test_drop_pattern_case_sensitive(self):
        """测试区分大小写"""
        df = pd.DataFrame({"text": ["ABC", "abc", "Abc"]})

        action = QuickFixAction(
            type="drop_rows_with_pattern",
            column="text",
            params={"pattern": "ABC", "case_sensitive": True},
        )

        result, _log = apply_actions(df, [action])

        assert len(result) == 2
        assert "ABC" not in result["text"].values
        assert "abc" in result["text"].values

    def test_drop_pattern_no_match(self):
        """测试无匹配"""
        df = pd.DataFrame({"status": ["active", "inactive"]})

        action = QuickFixAction(
            type="drop_rows_with_pattern", column="status", params={"pattern": "pending"}
        )

        result, log = apply_actions(df, [action])

        assert len(result) == 2
        assert log[0]["affected_rows"] == 0


class TestNormalizeUnits:
    """测试 normalize_units 动作"""

    def test_normalize_single_conversion(self):
        """测试单个单位转换"""
        df = pd.DataFrame({"glucose": [100, 180, 120], "unit": ["mg/dL", "mg/dL", "mmol/L"]})

        action = QuickFixAction(
            type="normalize_units",
            column="glucose",
            params={
                "unit_column": "unit",
                "conversions": {"mg/dL": {"factor": 0.0555, "target": "mmol/L"}},
            },
        )

        result, log = apply_actions(df, [action])

        # mg/dL 的值应该被转换
        assert abs(result.loc[0, "glucose"] - 5.55) < 0.01  # 100 * 0.0555
        assert abs(result.loc[1, "glucose"] - 9.99) < 0.01  # 180 * 0.0555
        # 已经是 mmol/L 的不变
        assert result.loc[2, "glucose"] == 120

        # 单位应该统一
        assert result.loc[0, "unit"] == "mmol/L"
        assert result.loc[1, "unit"] == "mmol/L"
        assert log[0]["affected_rows"] == 2

    def test_normalize_multiple_conversions(self):
        """测试多个单位转换"""
        df = pd.DataFrame({"value": [1.0, 1000.0, 1.0], "unit": ["g", "mg", "kg"]})

        action = QuickFixAction(
            type="normalize_units",
            column="value",
            params={
                "unit_column": "unit",
                "conversions": {
                    "mg": {"factor": 0.001, "target": "g"},
                    "kg": {"factor": 1000, "target": "g"},
                },
            },
        )

        result, _log = apply_actions(df, [action])

        assert result.loc[0, "value"] == 1.0  # 已经是 g
        assert result.loc[1, "value"] == 1.0  # 1000 mg = 1 g
        assert result.loc[2, "value"] == 1000.0  # 1 kg = 1000 g

        assert all(result["unit"] == "g")

    def test_normalize_missing_unit_column(self):
        """测试缺少单位列"""
        df = pd.DataFrame({"value": [1, 2, 3]})

        action = QuickFixAction(type="normalize_units", column="value", params={"conversions": {}})

        with pytest.raises(ValueError, match="unit_column"):
            apply_actions(df, [action])


class TestChainedActions:
    """测试链式动作"""

    def test_impute_then_winsorize(self):
        """测试先插补再截尾"""
        df = pd.DataFrame({"value": [10, 20, np.nan, 40, 1000]})

        actions = [
            QuickFixAction(type="impute_missing", column="value", params={"strategy": "median"}),
            QuickFixAction(type="winsorize_outliers", column="value", params={}),
        ]

        result, log = apply_actions(df, actions)

        # 应该没有缺失值
        assert result["value"].isna().sum() == 0
        # 极端值应该被截尾
        assert result["value"].max() < 1000

        # 两个动作都应该记录
        assert len(log) == 2
        assert log[0]["action"] == "impute_missing"
        assert log[1]["action"] == "winsorize_outliers"

    def test_rename_then_impute(self):
        """测试先重命名再插补"""
        df = pd.DataFrame({"old_name": [1, 2, np.nan]})

        actions = [
            QuickFixAction(
                type="rename_column", column="old_name", params={"new_name": "new_name"}
            ),
            QuickFixAction(type="impute_missing", column="new_name", params={"strategy": "median"}),
        ]

        result, _log = apply_actions(df, actions)

        assert "new_name" in result.columns
        assert "old_name" not in result.columns
        assert result["new_name"].isna().sum() == 0
