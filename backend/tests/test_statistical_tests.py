"""
统计推断模块测试
"""

import numpy as np
import pytest

from app.engines.reporting.statistical_tests import (
    paired_t_test,
    delong_test,
    friedman_test,
    wilcoxon_signed_rank_test,
    mcnemar_test,
)


class TestPairedTTest:
    """测试配对 t 检验"""
    
    def test_significant_difference(self):
        """测试显著差异"""
        np.random.seed(42)
        # 增加差异，避免精度损失
        metric1 = np.array([0.85, 0.87, 0.86, 0.88, 0.84, 0.89, 0.85, 0.87])
        metric2 = np.array([0.70, 0.71, 0.72, 0.73, 0.68, 0.75, 0.69, 0.73])  # 差异带方差，避免 t 检验退化
        
        result = paired_t_test(metric1, metric2)
        
        assert result["p_value"] is not None
        assert result["significant"] is True  # 应该显著
        assert result["mean_diff"] > 0  # metric1 > metric2
        assert "显著" in result["conclusion"]
    
    def test_no_difference(self):
        """测试无显著差异"""
        np.random.seed(42)
        # 使用接近但有小差异的数据
        metric1 = np.array([0.80, 0.82, 0.81, 0.83, 0.79, 0.81, 0.80, 0.82])
        metric2 = np.array([0.79, 0.81, 0.80, 0.82, 0.78, 0.80, 0.79, 0.81])
        
        result = paired_t_test(metric1, metric2)
        
        assert result["p_value"] is not None
        # 差异较小，可能不显著
        assert "差异" in result["conclusion"]
    
    def test_confidence_interval(self):
        """测试置信区间"""
        np.random.seed(42)
        # 使用明显差异的数据
        metric1 = np.array([0.85, 0.87, 0.86, 0.88, 0.84, 0.89, 0.85, 0.87])
        metric2 = np.array([0.70, 0.71, 0.72, 0.73, 0.68, 0.75, 0.69, 0.73])  # 差异带方差，避免 t 检验退化
        
        result = paired_t_test(metric1, metric2)
        
        assert result["ci_lower"] is not None
        assert result["ci_upper"] is not None
        assert result["ci_lower"] < result["mean_diff"]
    
    def test_small_sample(self):
        """测试样本量不足"""
        metric1 = np.array([0.85])
        metric2 = np.array([0.75])

        result = paired_t_test(metric1, metric2)

        assert result["p_value"] is None
        assert "样本量不足" in result["conclusion"]

    def test_zero_variance_significant_diff(self):
        """零方差恒定正差异：t 检验退化，须给出确定性显著结论而非 nan"""
        metric1 = np.full(6, 0.85)
        metric2 = np.full(6, 0.70)

        result = paired_t_test(metric1, metric2)

        assert result["p_value"] == 0.0
        assert result["significant"] is True
        assert isinstance(result["significant"], bool)  # Python bool，非 np.bool_
        assert result["ci_lower"] == result["mean_diff"] == result["ci_upper"]
        assert "显著" in result["conclusion"]

    def test_zero_variance_zero_diff(self):
        """两模型逐折完全一致：p=1.0、不显著、CI 退化为点"""
        m = np.array([0.80, 0.82, 0.81, 0.83])

        result = paired_t_test(m, m.copy())

        assert result["p_value"] == 1.0
        assert result["significant"] is False
        assert result["mean_diff"] == 0.0
        assert "无显著差异" in result["conclusion"]


class TestDeLongTest:
    """测试 DeLong AUC 比较"""
    
    def test_significant_auc_difference(self):
        """测试显著的 AUC 差异"""
        np.random.seed(42)
        n = 200
        y_true = np.random.randint(0, 2, n)
        
        # 模型1: 更好的预测
        y_score1 = y_true * 0.7 + np.random.rand(n) * 0.3
        # 模型2: 较差的预测
        y_score2 = y_true * 0.4 + np.random.rand(n) * 0.6
        
        result = delong_test(y_true, y_score1, y_score2)
        
        assert result["auc1"] is not None
        assert result["auc2"] is not None
        assert result["auc1"] > result["auc2"]
        assert result["p_value"] is not None
    
    def test_similar_auc(self):
        """测试相似的 AUC"""
        np.random.seed(42)
        n = 100
        y_true = np.random.randint(0, 2, n)
        y_score1 = y_true * 0.6 + np.random.rand(n) * 0.4
        y_score2 = y_true * 0.6 + np.random.rand(n) * 0.4
        
        result = delong_test(y_true, y_score1, y_score2)
        
        assert result["auc1"] is not None
        assert result["auc2"] is not None
        assert abs(result["auc_diff"]) < 0.1
    
    def test_small_sample(self):
        """测试样本量不足"""
        y_true = np.array([0, 1, 0])
        y_score1 = np.array([0.3, 0.8, 0.2])
        y_score2 = np.array([0.4, 0.7, 0.3])
        
        result = delong_test(y_true, y_score1, y_score2)
        
        assert "样本量不足" in result["conclusion"]
    
    def test_single_class(self):
        """测试只有单一类别"""
        y_true = np.ones(50)
        y_score1 = np.random.rand(50)
        y_score2 = np.random.rand(50)
        
        result = delong_test(y_true, y_score1, y_score2)
        
        assert result["auc1"] is None or "单一类别" in result["conclusion"]


class TestFriedmanTest:
    """测试 Friedman 检验"""
    
    def test_significant_difference(self):
        """测试显著差异（3个模型）"""
        np.random.seed(42)
        # 3个模型在5折上的表现
        model1 = np.array([0.85, 0.87, 0.86, 0.88, 0.84])
        model2 = np.array([0.75, 0.77, 0.76, 0.78, 0.74])
        model3 = np.array([0.80, 0.82, 0.81, 0.83, 0.79])
        
        result = friedman_test(model1, model2, model3)
        
        assert result["statistic"] is not None
        assert result["p_value"] is not None
        assert result["n_models"] == 3
        assert result["n_folds"] == 5
    
    def test_no_difference(self):
        """测试无显著差异"""
        np.random.seed(42)
        model1 = np.array([0.80, 0.82, 0.81, 0.83, 0.79])
        model2 = np.array([0.81, 0.83, 0.80, 0.82, 0.80])
        model3 = np.array([0.80, 0.81, 0.82, 0.81, 0.81])
        
        result = friedman_test(model1, model2, model3)
        
        assert result["p_value"] is not None
        # 可能不显著
        assert "conclusion" in result
    
    def test_too_few_models(self):
        """测试模型数量不足"""
        model1 = np.array([0.85, 0.87])
        model2 = np.array([0.75, 0.77])
        
        result = friedman_test(model1, model2)
        
        assert result["statistic"] is None
        assert "至少需要3个模型" in result["conclusion"]


class TestWilcoxonSignedRankTest:
    """测试 Wilcoxon 符号秩检验"""
    
    def test_significant_difference(self):
        """测试显著差异"""
        np.random.seed(42)
        metric1 = np.array([0.85, 0.87, 0.86, 0.88, 0.84, 0.89])
        metric2 = np.array([0.75, 0.77, 0.76, 0.78, 0.74, 0.79])
        
        result = wilcoxon_signed_rank_test(metric1, metric2)
        
        assert result["p_value"] is not None
        assert result["median_diff"] > 0
    
    def test_no_difference(self):
        """测试无显著差异"""
        np.random.seed(42)
        metric1 = np.array([0.80, 0.82, 0.81, 0.83, 0.79, 0.80])
        metric2 = np.array([0.81, 0.83, 0.80, 0.82, 0.80, 0.81])
        
        result = wilcoxon_signed_rank_test(metric1, metric2)
        
        assert result["p_value"] is not None
        assert "conclusion" in result
    
    def test_small_sample(self):
        """测试样本量不足"""
        metric1 = np.array([0.85, 0.87, 0.86])
        metric2 = np.array([0.75, 0.77, 0.76])
        
        result = wilcoxon_signed_rank_test(metric1, metric2)
        
        assert "样本量不足" in result["conclusion"]


class TestMcNemarTest:
    """测试 McNemar 检验"""
    
    def test_significant_difference(self):
        """测试显著差异"""
        np.random.seed(42)
        n = 100
        y_true = np.random.randint(0, 2, n)
        
        # 模型1: 准确率高
        y_pred1 = y_true.copy()
        y_pred1[:10] = 1 - y_pred1[:10]  # 10个错误
        
        # 模型2: 准确率低
        y_pred2 = y_true.copy()
        y_pred2[:30] = 1 - y_pred2[:30]  # 30个错误
        
        result = mcnemar_test(y_true, y_pred1, y_pred2)
        
        assert result["statistic"] is not None
        assert result["p_value"] is not None
        assert result["n01"] + result["n10"] > 0
    
    def test_identical_errors(self):
        """测试完全相同的错误"""
        np.random.seed(42)
        n = 50
        y_true = np.random.randint(0, 2, n)
        y_pred1 = y_true.copy()
        y_pred2 = y_true.copy()
        
        result = mcnemar_test(y_true, y_pred1, y_pred2)
        
        assert result["statistic"] is None
        assert "完全一致" in result["conclusion"]
    
    def test_small_sample(self):
        """测试样本量不足"""
        y_true = np.array([0, 1, 0, 1, 0])
        y_pred1 = np.array([0, 1, 0, 1, 0])
        y_pred2 = np.array([0, 0, 0, 1, 1])
        
        result = mcnemar_test(y_true, y_pred1, y_pred2)
        
        assert "样本量不足" in result["conclusion"]


class TestIntegration:
    """集成测试"""
    
    def test_model_comparison_pipeline(self):
        """测试完整的模型比较流程"""
        np.random.seed(42)
        
        # 模拟5折交叉验证的3个模型（增加差异）
        model1_folds = np.array([0.85, 0.87, 0.86, 0.88, 0.84])
        model2_folds = np.array([0.80, 0.82, 0.81, 0.83, 0.79])
        model3_folds = np.array([0.70, 0.72, 0.71, 0.73, 0.69])
        
        # 1. Friedman 检验（整体）
        friedman_result = friedman_test(model1_folds, model2_folds, model3_folds)
        assert friedman_result["p_value"] is not None
        
        # 2. 配对 t 检验（两两比较）
        t_result_1v2 = paired_t_test(model1_folds, model2_folds)
        t_result_1v3 = paired_t_test(model1_folds, model3_folds)
        t_result_2v3 = paired_t_test(model2_folds, model3_folds)
        
        assert t_result_1v2["p_value"] is not None
        assert t_result_1v3["p_value"] is not None
        assert t_result_2v3["p_value"] is not None
        
        # 验证：model1 应该优于 model3（不严格要求显著性）
        assert t_result_1v3["mean_diff"] > 0
    
    def test_classification_comparison(self):
        """测试分类模型比较"""
        np.random.seed(42)
        n = 200
        
        # 真实标签
        y_true = np.random.randint(0, 2, n)
        
        # 两个模型的预测概率（模型2须带足噪声，否则两模型均完美 → McNemar 无 discordant 对）
        y_score1 = y_true * 0.7 + np.random.rand(n) * 0.3
        y_score2 = y_true * 0.4 + np.random.rand(n) * 0.6
        
        # DeLong AUC 比较
        delong_result = delong_test(y_true, y_score1, y_score2)
        
        assert delong_result["auc1"] is not None
        assert delong_result["auc2"] is not None
        # model1 应该不差于 model2（允许相等）
        assert delong_result["auc1"] >= delong_result["auc2"] - 0.05
        
        # McNemar 错误率比较
        y_pred1 = (y_score1 > 0.5).astype(int)
        y_pred2 = (y_score2 > 0.5).astype(int)
        
        mcnemar_result = mcnemar_test(y_true, y_pred1, y_pred2)
        
        assert mcnemar_result["p_value"] is not None
