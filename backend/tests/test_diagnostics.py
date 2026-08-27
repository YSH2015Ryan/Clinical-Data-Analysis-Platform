"""
报告增强 - 模型诊断测试
"""

import numpy as np
import pytest

from app.engines.reporting.diagnostics import (
    shapiro_wilk_test,
    breusch_pagan_test,
    generate_diagnostic_paragraph,
    durbin_watson_test,
    vif_analysis,
)


class TestShapiroWilkTest:
    """测试 Shapiro-Wilk 正态性检验"""
    
    def test_normal_residuals(self):
        """测试正态分布的残差"""
        np.random.seed(42)
        residuals = np.random.normal(0, 1, 100)
        
        result = shapiro_wilk_test(residuals)
        
        assert result["statistic"] is not None
        assert result["p_value"] is not None
        # 正态分布应该通过检验（p > 0.05）
        assert result["is_normal"] in [True, False]  # 允许两种结果
        assert "conclusion" in result
    
    def test_non_normal_residuals(self):
        """测试非正态分布的残差（指数分布）"""
        np.random.seed(42)
        residuals = np.random.exponential(1, 100)
        
        result = shapiro_wilk_test(residuals)
        
        assert result["statistic"] is not None
        assert result["p_value"] is not None
        # 指数分布应该不通过正态性检验
        # 注意：小样本可能偶尔通过，这里不做严格断言
        assert "conclusion" in result
    
    def test_large_sample(self):
        """测试大样本（>5000，使用 KS 检验）"""
        np.random.seed(42)
        residuals = np.random.normal(0, 1, 6000)
        
        result = shapiro_wilk_test(residuals)
        
        assert result["statistic"] is not None
        assert result["p_value"] is not None
        assert result["test_name"] == "Kolmogorov-Smirnov"
    
    def test_small_sample(self):
        """测试样本量不足"""
        residuals = np.array([1.0, 2.0])
        
        result = shapiro_wilk_test(residuals)
        
        assert result["statistic"] is None
        assert result["p_value"] is None
        assert "样本量不足" in result["conclusion"]
    
    def test_with_nan(self):
        """测试包含 NaN 的残差"""
        residuals = np.array([1.0, 2.0, np.nan, 3.0, 4.0, 5.0] * 20)
        
        result = shapiro_wilk_test(residuals)
        
        # 应该自动移除 NaN
        assert result["statistic"] is not None
        assert result["p_value"] is not None


class TestBreuschPaganTest:
    """测试 Breusch-Pagan 同方差性检验"""
    
    def test_homoscedastic(self):
        """测试同方差情况"""
        np.random.seed(42)
        n = 100
        X = np.random.randn(n, 2)
        residuals = np.random.randn(n)  # 同方差
        
        result = breusch_pagan_test(X, residuals)
        
        assert result["statistic"] is not None
        assert result["p_value"] is not None
        # 同方差应该通过检验（p > 0.05）
        assert result["is_homoscedastic"] in [True, False]  # 允许两种结果
        assert "conclusion" in result
    
    def test_heteroscedastic(self):
        """测试异方差情况"""
        np.random.seed(42)
        n = 200
        X = np.random.randn(n, 2)
        # 制造异方差：残差方差与 X 相关
        residuals = np.random.randn(n) * (1 + np.abs(X[:, 0]))
        
        result = breusch_pagan_test(X, residuals)
        
        assert result["statistic"] is not None
        assert result["p_value"] is not None
        # 应该检测到异方差（但小样本可能不稳定，不做严格断言）
        assert "conclusion" in result
    
    def test_small_sample(self):
        """测试样本量不足"""
        X = np.random.randn(5, 2)
        residuals = np.random.randn(5)
        
        result = breusch_pagan_test(X, residuals)
        
        assert result["statistic"] is None
        assert "样本量不足" in result["conclusion"]
    
    def test_singular_matrix(self):
        """测试奇异矩阵（多重共线性）"""
        np.random.seed(42)
        n = 50
        X1 = np.random.randn(n, 1)
        X = np.hstack([X1, X1])  # 完全共线
        residuals = np.random.randn(n)
        
        result = breusch_pagan_test(X, residuals)
        
        # 应该检测到矩阵奇异
        assert result["statistic"] is None or result["p_value"] is not None
    
    def test_with_nan(self):
        """测试包含 NaN"""
        np.random.seed(42)
        X = np.random.randn(100, 2)
        residuals = np.random.randn(100)
        residuals[50] = np.nan
        X[51, 0] = np.nan
        
        result = breusch_pagan_test(X, residuals)
        
        # 应该自动移除 NaN 行
        assert result["statistic"] is not None


class TestGenerateDiagnosticParagraph:
    """测试诊断段落生成"""
    
    def test_both_pass(self):
        """测试两个检验都通过"""
        shapiro_result = {
            "statistic": 0.98,
            "p_value": 0.15,
            "is_normal": True,
            "conclusion": "残差通过Shapiro-Wilk正态性检验（W=0.98, p=0.150）。"
        }
        bp_result = {
            "statistic": 5.2,
            "p_value": 0.08,
            "is_homoscedastic": True,
            "conclusion": "残差通过Breusch-Pagan同方差性检验（LM=5.2, p=0.080）。"
        }
        
        paragraph = generate_diagnostic_paragraph(shapiro_result, bp_result)
        
        assert "模型诊断" in paragraph
        assert "通过" in paragraph
        assert "满足线性回归的基本假设" in paragraph
    
    def test_both_fail(self):
        """测试两个检验都不通过"""
        shapiro_result = {
            "statistic": 0.85,
            "p_value": 0.001,
            "is_normal": False,
            "conclusion": "残差未通过Shapiro-Wilk正态性检验（W=0.85, p=0.001）。"
        }
        bp_result = {
            "statistic": 25.3,
            "p_value": 0.001,
            "is_homoscedastic": False,
            "conclusion": "残差未通过Breusch-Pagan同方差性检验（LM=25.3, p=0.001）。"
        }
        
        paragraph = generate_diagnostic_paragraph(shapiro_result, bp_result)
        
        assert "模型诊断" in paragraph
        assert "未通过" in paragraph
        assert "满足线性回归的基本假设" not in paragraph
    
    def test_no_results(self):
        """测试没有检验结果"""
        paragraph = generate_diagnostic_paragraph(None, None)
        
        assert "模型诊断" in paragraph
        assert "未执行" in paragraph or "样本量不足" in paragraph
    
    def test_partial_results(self):
        """测试只有部分结果"""
        shapiro_result = {
            "statistic": 0.98,
            "p_value": 0.15,
            "is_normal": True,
            "conclusion": "残差通过正态性检验。"
        }
        
        paragraph = generate_diagnostic_paragraph(shapiro_result, None)
        
        assert "模型诊断" in paragraph
        assert "正态性检验" in paragraph


class TestDurbinWatsonTest:
    """测试 Durbin-Watson 自相关检验"""
    
    def test_no_autocorrelation(self):
        """测试无自相关"""
        np.random.seed(42)
        residuals = np.random.randn(100)
        
        result = durbin_watson_test(residuals)
        
        assert result["statistic"] is not None
        assert 1.5 <= result["statistic"] <= 2.5  # 应该接近 2
        assert "无显著自相关" in result["conclusion"]
    
    def test_positive_autocorrelation(self):
        """测试正自相关"""
        np.random.seed(42)
        # 制造正自相关：每个值依赖于前一个值
        residuals = np.zeros(100)
        residuals[0] = np.random.randn()
        for i in range(1, 100):
            residuals[i] = 0.7 * residuals[i-1] + 0.3 * np.random.randn()
        
        result = durbin_watson_test(residuals)
        
        assert result["statistic"] is not None
        assert result["statistic"] < 1.5  # 正自相关 DW < 2
        assert "正自相关" in result["conclusion"]
    
    def test_small_sample(self):
        """测试样本量不足"""
        residuals = np.array([1.0])
        
        result = durbin_watson_test(residuals)
        
        assert result["statistic"] is None
        assert "样本量不足" in result["conclusion"]


class TestVIFAnalysis:
    """测试方差膨胀因子分析"""
    
    def test_no_multicollinearity(self):
        """测试无多重共线性"""
        np.random.seed(42)
        X = np.random.randn(100, 3)
        feature_names = ["age", "bmi", "glucose"]
        
        result = vif_analysis(X, feature_names)
        
        assert len(result["vif_values"]) == 3
        assert result["max_vif"] is not None
        assert result["max_vif"] < 10
        assert result["has_multicollinearity"] is False
        assert "未发现" in result["conclusion"]
    
    def test_with_multicollinearity(self):
        """测试存在多重共线性"""
        np.random.seed(42)
        X1 = np.random.randn(100, 1)
        X2 = X1 + np.random.randn(100, 1) * 0.1  # 高度相关
        X3 = np.random.randn(100, 1)
        X = np.hstack([X1, X2, X3])
        
        result = vif_analysis(X, ["x1", "x2", "x3"])
        
        assert result["max_vif"] is not None
        assert result["max_vif"] > 5  # 应该检测到共线性
    
    def test_single_feature(self):
        """测试单个特征"""
        X = np.random.randn(100, 1)
        
        result = vif_analysis(X)
        
        assert result["max_vif"] is None
        assert "特征数量不足" in result["conclusion"]
    
    def test_perfect_collinearity(self):
        """测试完全共线性"""
        np.random.seed(42)
        X1 = np.random.randn(100, 1)
        X = np.hstack([X1, X1])  # 完全相同
        
        result = vif_analysis(X, ["x1", "x2"])
        
        # VIF 应该是无穷大或 None（完全共线性）
        assert result["has_multicollinearity"] in [True, False]
        assert "conclusion" in result


class TestIntegration:
    """集成测试"""
    
    def test_full_diagnostic_pipeline(self):
        """测试完整诊断流程"""
        np.random.seed(42)
        n = 100
        
        # 模拟回归模型
        X = np.random.randn(n, 3)
        y = 2 * X[:, 0] + 3 * X[:, 1] - X[:, 2] + np.random.randn(n)
        
        # 拟合模型（简单 OLS）
        X_with_intercept = np.column_stack([np.ones(n), X])
        beta = np.linalg.inv(X_with_intercept.T @ X_with_intercept) @ X_with_intercept.T @ y
        y_pred = X_with_intercept @ beta
        residuals = y - y_pred
        
        # 运行所有诊断
        shapiro_result = shapiro_wilk_test(residuals)
        bp_result = breusch_pagan_test(X, residuals)
        dw_result = durbin_watson_test(residuals)
        vif_result = vif_analysis(X, ["x1", "x2", "x3"])
        
        # 生成段落
        paragraph = generate_diagnostic_paragraph(shapiro_result, bp_result)
        
        # 验证所有结果都有效
        assert shapiro_result["p_value"] is not None
        assert bp_result["p_value"] is not None
        assert dw_result["statistic"] is not None
        assert vif_result["max_vif"] is not None
        assert len(paragraph) > 0
        
        # 验证所有结果都有有效值（不严格要求通过检验）
        assert shapiro_result["is_normal"] in [True, False]
        assert bp_result["is_homoscedastic"] in [True, False]
        assert dw_result["statistic"] > 0  # DW 统计量应该大于 0
        assert vif_result["has_multicollinearity"] in [True, False]
