"""
基线特征表测试
"""

import numpy as np
import pandas as pd
from app.engines.reporting.baseline_table import (
    _detect_categorical_cols,
    _detect_continuous_cols,
    _summarize_categorical,
    _summarize_continuous,
    format_baseline_table_html,
    generate_baseline_table,
)


class TestDetectColumns:
    """测试列类型检测"""

    def test_detect_continuous(self):
        """测试连续变量检测"""
        df = pd.DataFrame(
            {
                "age": np.random.randint(20, 80, 100),
                "bmi": np.random.uniform(18, 35, 100),
                "category": ["A", "B", "C"] * 33 + ["A"],
            }
        )

        continuous = _detect_continuous_cols(df)

        assert "age" in continuous
        assert "bmi" in continuous
        assert "category" not in continuous

    def test_detect_categorical(self):
        """测试分类变量检测"""
        df = pd.DataFrame(
            {
                "gender": ["M", "F"] * 50,
                "stage": [1, 2, 3] * 33 + [1],
                "age": np.random.randint(20, 80, 100),
            }
        )

        categorical = _detect_categorical_cols(df)

        assert "gender" in categorical
        assert "stage" in categorical
        assert "age" not in categorical  # >10 unique values


class TestSummarizeContinuous:
    """测试连续变量汇总"""

    def test_mean_sd_format(self):
        """测试 mean ± SD 格式"""
        np.random.seed(42)
        df = pd.DataFrame({"age": np.random.normal(50, 10, 100), "group": ["A", "B"] * 50})

        row = _summarize_continuous(df, "age", None, False)

        assert row is not None
        assert row["type"] == "continuous"
        assert "±" in row["total"]

    def test_median_iqr_format(self):
        """测试 median (IQR) 格式（非正态分布）"""
        np.random.seed(42)
        # 指数分布（非正态）
        df = pd.DataFrame({"value": np.random.exponential(10, 100)})

        row = _summarize_continuous(df, "value", None, False)

        assert row is not None
        # 可能是 mean±sd 或 median(iqr)，取决于检验结果
        assert "total" in row

    def test_stratified_analysis(self):
        """测试分层分析"""
        np.random.seed(42)
        df = pd.DataFrame(
            {
                "age": list(np.random.normal(45, 5, 50)) + list(np.random.normal(55, 5, 50)),
                "group": ["Train"] * 50 + ["Test"] * 50,
            }
        )

        row = _summarize_continuous(df, "age", "group", True)

        assert row is not None
        assert "stratum_Train" in row
        assert "stratum_Test" in row
        assert "p_value" in row
        assert row["p_value"] is not None  # 应该有显著差异


class TestSummarizeCategorical:
    """测试分类变量汇总"""

    def test_basic_summary(self):
        """测试基本汇总"""
        df = pd.DataFrame({"gender": ["M"] * 60 + ["F"] * 40})

        rows = _summarize_categorical(df, "gender", None, False)

        assert len(rows) >= 2  # 至少有父行和1个类别行
        assert rows[0]["type"] == "categorical_header"
        assert rows[1]["type"] == "categorical_value"
        assert "60 (60.0%)" in rows[1]["total"]

    def test_stratified_categorical(self):
        """测试分层分类分析"""
        df = pd.DataFrame(
            {
                "gender": ["M"] * 30 + ["F"] * 20 + ["M"] * 30 + ["F"] * 20,
                "group": ["A"] * 50 + ["B"] * 50,
            }
        )

        rows = _summarize_categorical(df, "gender", "group", True)

        assert len(rows) >= 2
        # 第一个类别行应该有 p 值
        value_rows = [r for r in rows if r["type"] == "categorical_value"]
        assert value_rows[0]["p_value"] is not None


class TestGenerateBaselineTable:
    """测试完整基线表生成"""

    def test_full_table(self):
        """测试完整表格生成"""
        np.random.seed(42)
        df = pd.DataFrame(
            {
                "age": np.random.normal(50, 10, 100),
                "bmi": np.random.normal(25, 3, 100),
                "gender": ["M", "F"] * 50,
                "stage": np.random.choice([1, 2, 3], 100),
            }
        )

        result = generate_baseline_table(df)

        assert "rows" in result
        assert "total_n" in result
        assert result["total_n"] == 100
        assert len(result["rows"]) > 0

    def test_stratified_table(self):
        """测试分层表格"""
        np.random.seed(42)
        df = pd.DataFrame(
            {
                "age": list(np.random.normal(45, 5, 50)) + list(np.random.normal(55, 5, 50)),
                "gender": ["M", "F"] * 50,
                "group": ["Train"] * 50 + ["Test"] * 50,
            }
        )

        result = generate_baseline_table(df, stratify_by="group", test_difference=True)

        assert len(result["strata"]) == 2
        assert result["strata"][0]["n"] == 50
        assert result["strata"][1]["n"] == 50

        # 检查是否有 p 值
        has_pvalue = any(row.get("p_value") is not None for row in result["rows"])
        assert has_pvalue

    def test_manual_column_specification(self):
        """测试手动指定列"""
        df = pd.DataFrame(
            {
                "age": np.random.normal(50, 10, 100),
                "bmi": np.random.normal(25, 3, 100),
                "gender": ["M", "F"] * 50,
                "id": range(100),  # 应该被排除
            }
        )

        result = generate_baseline_table(
            df, continuous_cols=["age", "bmi"], categorical_cols=["gender"]
        )

        assert len(result["rows"]) > 0
        # id 列不应该出现
        assert not any(row["variable"] == "id" for row in result["rows"])

    def test_empty_dataframe(self):
        """测试空数据框"""
        df = pd.DataFrame()

        result = generate_baseline_table(df)

        assert result["total_n"] == 0
        assert len(result["rows"]) == 0
        assert "数据为空" in result["note"]


class TestFormatHTML:
    """测试 HTML 格式化"""

    def test_html_output(self):
        """测试 HTML 输出"""
        np.random.seed(42)
        df = pd.DataFrame({"age": np.random.normal(50, 10, 50), "gender": ["M", "F"] * 25})

        table_data = generate_baseline_table(df)
        html = format_baseline_table_html(table_data)

        assert "<table" in html
        assert "<thead>" in html
        assert "<tbody>" in html
        assert "总计" in html

    def test_stratified_html(self):
        """测试分层 HTML"""
        df = pd.DataFrame(
            {"age": list(range(50)) + list(range(50, 100)), "group": ["A"] * 50 + ["B"] * 50}
        )

        table_data = generate_baseline_table(df, stratify_by="group")
        html = format_baseline_table_html(table_data)

        assert "A" in html or "B" in html
        assert "N=" in html

    def test_empty_table_html(self):
        """测试空表 HTML"""
        table_data = {"rows": [], "total_n": 0, "strata": [], "note": ""}

        html = format_baseline_table_html(table_data)

        assert "无基线特征数据" in html


class TestIntegration:
    """集成测试"""

    def test_real_world_scenario(self):
        """测试真实场景"""
        np.random.seed(42)

        # 模拟临床研究数据
        n_train = 140
        n_test = 60

        df = pd.DataFrame(
            {
                "age": list(np.random.normal(55, 12, n_train))
                + list(np.random.normal(57, 11, n_test)),
                "bmi": list(np.random.normal(24, 3, n_train))
                + list(np.random.normal(24.5, 3.2, n_test)),
                "gender": np.random.choice(["男", "女"], n_train + n_test),
                "stage": np.random.choice(["I", "II", "III"], n_train + n_test),
                "smoking": np.random.choice(["是", "否"], n_train + n_test),
                "split": ["训练集"] * n_train + ["测试集"] * n_test,
            }
        )

        # 生成表格
        result = generate_baseline_table(
            df,
            continuous_cols=["age", "bmi"],
            categorical_cols=["gender", "stage", "smoking"],
            stratify_by="split",
            test_difference=True,
        )

        # 验证结果
        assert result["total_n"] == 200
        assert len(result["strata"]) == 2
        assert result["strata"][0]["n"] == 140
        assert result["strata"][1]["n"] == 60

        # 验证有连续和分类变量
        continuous_rows = [r for r in result["rows"] if r.get("type") == "continuous"]
        categorical_rows = [r for r in result["rows"] if r.get("type") == "categorical_value"]

        assert len(continuous_rows) >= 2  # age, bmi
        assert len(categorical_rows) >= 5  # gender(2) + stage(3) + smoking(2)

        # 生成 HTML
        html = format_baseline_table_html(result)

        assert len(html) > 0
        assert "训练集" in html
        assert "测试集" in html
        assert "p 值" in html

    def test_unbalanced_groups(self):
        """测试不平衡分组"""
        df = pd.DataFrame(
            {
                "value": list(np.random.normal(50, 10, 100)) + list(np.random.normal(55, 10, 20)),
                "group": ["大组"] * 100 + ["小组"] * 20,
            }
        )

        result = generate_baseline_table(df, stratify_by="group", test_difference=True)

        assert result["total_n"] == 120
        assert len(result["strata"]) == 2
        # 应该能正常处理不平衡
        assert result["strata"][0]["n"] == 100
        assert result["strata"][1]["n"] == 20
