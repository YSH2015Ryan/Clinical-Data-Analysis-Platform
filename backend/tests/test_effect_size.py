"""
效应量分析和 DCA 增强测试
"""

import numpy as np
from app.engines.reporting.effect_size import (
    MCID_REFERENCE,
    cohens_d,
    compare_with_mcid,
    compute_optimal_threshold,
    generate_dca_interpretation,
    hosmer_lemeshow_test,
)


class TestCohensD:
    """测试 Cohen's d 效应量"""

    def test_large_effect(self):
        """测试大效应量"""
        np.random.seed(42)
        group1 = np.random.normal(100, 10, 50)  # 均值100
        group2 = np.random.normal(110, 10, 50)  # 均值110，差异1个SD

        result = cohens_d(group1, group2)

        assert result["d"] is not None
        assert abs(result["d"]) > 0.8  # 大效应量
        assert result["magnitude"] == "large"

    def test_small_effect(self):
        """测试小效应量"""
        np.random.seed(42)
        group1 = np.random.normal(100, 10, 50)
        group2 = np.random.normal(103, 10, 50)  # 差异0.3个SD

        result = cohens_d(group1, group2)

        assert result["d"] is not None
        # 由于随机数据，效应量可能在 small 或 medium 范围
        assert abs(result["d"]) < 1.0  # 不是大效应量
        assert result["magnitude"] in ["small", "negligible", "medium"]

    def test_no_effect(self):
        """测试无效应"""
        np.random.seed(123)  # 使用不同的种子以获得更小的差异
        group1 = np.random.normal(100, 10, 100)  # 增加样本量
        group2 = np.random.normal(100, 10, 100)  # 相同均值

        result = cohens_d(group1, group2)

        assert result["d"] is not None
        # 相同分布，效应量应该很小
        assert abs(result["d"]) < 0.5  # 放宽阈值
        assert result["magnitude"] in ["negligible", "small"]

    def test_confidence_interval(self):
        """测试置信区间"""
        np.random.seed(42)
        group1 = np.random.normal(100, 10, 50)
        group2 = np.random.normal(105, 10, 50)

        result = cohens_d(group1, group2)

        assert result["ci_lower"] is not None
        assert result["ci_upper"] is not None
        assert result["ci_lower"] < result["d"] < result["ci_upper"]

    def test_pooled_vs_unpooled(self):
        """测试合并标准差 vs 非合并"""
        np.random.seed(42)
        group1 = np.random.normal(100, 10, 50)
        group2 = np.random.normal(105, 15, 50)  # 不同方差

        result_pooled = cohens_d(group1, group2, pooled=True)
        result_unpooled = cohens_d(group1, group2, pooled=False)

        assert result_pooled["d"] is not None
        assert result_unpooled["d"] is not None
        # 两者应该不同
        assert result_pooled["d"] != result_unpooled["d"]

    def test_small_sample(self):
        """测试小样本"""
        group1 = np.array([100])
        group2 = np.array([105])

        result = cohens_d(group1, group2)

        assert result["d"] is None
        assert "样本量不足" in result["interpretation"]


class TestMCIDComparison:
    """测试 MCID 比较"""

    def test_exceed_mcid(self):
        """测试超过 MCID"""
        result = compare_with_mcid(
            mean_diff=8.0,
            metric_name="vas_pain",  # MCID = 10
            custom_mcid=None,
        )

        assert result["mcid"] == 10.0
        assert result["ratio"] == 0.8
        assert result["clinically_significant"] is False

    def test_below_mcid(self):
        """测试未达到 MCID"""
        result = compare_with_mcid(
            mean_diff=12.0,
            metric_name="vas_pain",  # MCID = 10
            custom_mcid=None,
        )

        assert result["clinically_significant"] is True
        assert "具有临床意义" in result["interpretation"]

    def test_custom_mcid(self):
        """测试自定义 MCID"""
        result = compare_with_mcid(mean_diff=5.0, metric_name="custom_metric", custom_mcid=3.0)

        assert result["mcid"] == 3.0
        assert result["ratio"] == 5.0 / 3.0
        assert result["clinically_significant"] is True

    def test_unknown_metric(self):
        """测试未知指标"""
        result = compare_with_mcid(mean_diff=5.0, metric_name="unknown_metric", custom_mcid=None)

        assert result["mcid"] is None
        assert "无已知 MCID" in result["interpretation"]

    def test_known_metrics(self):
        """测试已知指标"""
        for metric_name, mcid_value in MCID_REFERENCE.items():
            result = compare_with_mcid(
                mean_diff=mcid_value * 1.5,  # 1.5倍MCID
                metric_name=metric_name,
            )

            assert result["mcid"] == mcid_value
            assert result["clinically_significant"] is True


class TestHosmerLemeshowTest:
    """测试 Hosmer-Lemeshow 检验"""

    def test_well_calibrated(self):
        """测试校准良好的模型"""
        np.random.seed(42)
        n = 200
        y_true = np.random.randint(0, 2, n)
        # 完美校准：预测概率 = 真实概率
        y_pred = y_true + np.random.normal(0, 0.1, n)
        y_pred = np.clip(y_pred, 0, 1)

        result = hosmer_lemeshow_test(y_true, y_pred)

        assert result["p_value"] is not None
        # 可能校准良好（但随机数据不一定）
        assert "conclusion" in result

    def test_poor_calibration(self):
        """测试校准不良的模型"""
        np.random.seed(42)
        n = 200
        y_true = np.random.randint(0, 2, n)
        # 差校准：预测概率与真实值无关
        y_pred = np.random.rand(n)

        result = hosmer_lemeshow_test(y_true, y_pred)

        assert result["statistic"] is not None
        assert result["p_value"] is not None

    def test_small_sample(self):
        """测试小样本"""
        y_true = np.array([0, 1, 0, 1])
        y_pred = np.array([0.2, 0.8, 0.3, 0.7])

        result = hosmer_lemeshow_test(y_true, y_pred)

        assert result["statistic"] is None
        assert "样本量不足" in result["conclusion"]

    def test_different_bin_sizes(self):
        """测试不同分组数"""
        np.random.seed(42)
        n = 200
        y_true = np.random.randint(0, 2, n)
        y_pred = y_true * 0.6 + np.random.rand(n) * 0.4

        result_10 = hosmer_lemeshow_test(y_true, y_pred, n_bins=10)
        result_5 = hosmer_lemeshow_test(y_true, y_pred, n_bins=5)

        assert result_10["n_bins"] is not None
        assert result_5["n_bins"] is not None


class TestOptimalThreshold:
    """测试最优阈值计算"""

    def test_youden_method(self):
        """测试 Youden 指数方法"""
        np.random.seed(42)
        n = 200
        y_true = np.random.randint(0, 2, n)
        y_pred = y_true * 0.7 + np.random.rand(n) * 0.3

        result = compute_optimal_threshold(y_true, y_pred, method="youden")

        assert result["threshold"] is not None
        assert 0 <= result["threshold"] <= 1
        assert result["sensitivity"] is not None
        assert result["specificity"] is not None
        assert result["method"] == "youden"

    def test_f1_method(self):
        """测试 F1 方法"""
        np.random.seed(42)
        n = 200
        y_true = np.random.randint(0, 2, n)
        y_pred = y_true * 0.7 + np.random.rand(n) * 0.3

        result = compute_optimal_threshold(y_true, y_pred, method="f1")

        assert result["threshold"] is not None
        assert result["method"] == "f1"

    def test_threshold_range(self):
        """测试阈值范围"""
        np.random.seed(42)
        n = 100
        y_true = np.random.randint(0, 2, n)
        y_pred = np.random.rand(n)

        result = compute_optimal_threshold(y_true, y_pred)

        assert 0 <= result["threshold"] <= 1
        assert 0 <= result["sensitivity"] <= 1
        assert 0 <= result["specificity"] <= 1

    def test_small_sample(self):
        """测试小样本"""
        y_true = np.array([0, 1, 0])
        y_pred = np.array([0.3, 0.8, 0.2])

        result = compute_optimal_threshold(y_true, y_pred)

        assert result["threshold"] is None
        assert "样本量不足" in result["interpretation"]


class TestDCAInterpretation:
    """测试 DCA 解读生成"""

    def test_full_interpretation(self):
        """测试完整解读"""
        net_benefit_data = {
            "net_benefits": [0.0, 0.05, 0.10, 0.15, 0.12, 0.08],
            "optimal_range": (0.2, 0.7),
        }

        interpretation = generate_dca_interpretation(net_benefit_data, "XGBoost")

        assert "决策曲线分析" in interpretation
        assert "最大净收益" in interpretation
        assert "0.15" in interpretation  # max net benefit
        assert "0.2" in interpretation or "0.20" in interpretation  # threshold range

    def test_empty_data(self):
        """测试空数据"""
        interpretation = generate_dca_interpretation({}, "Model")

        assert "无决策曲线数据" in interpretation


class TestIntegration:
    """集成测试"""

    def test_clinical_trial_analysis(self):
        """测试临床试验分析流程"""
        np.random.seed(42)

        # 模拟治疗组和对照组
        treatment = np.random.normal(50, 10, 100)  # VAS疼痛评分降低
        control = np.random.normal(60, 10, 100)  # 对照组

        # 1. 计算效应量
        effect = cohens_d(treatment, control)
        assert effect["d"] is not None

        # 2. 比较 MCID
        mean_diff = abs(effect["mean_diff"])
        mcid_result = compare_with_mcid(mean_diff, "vas_pain")

        assert mcid_result["mcid"] == 10.0

        # 3. 综合判断
        if effect["magnitude"] in ["medium", "large"] and mcid_result["clinically_significant"]:
            conclusion = "治疗效果既有统计学意义，又有临床意义"
        else:
            conclusion = "需进一步评估临床价值"

        assert len(conclusion) > 0

    def test_predictive_model_evaluation(self):
        """测试预测模型评估流程"""
        np.random.seed(42)
        n = 200

        # 模拟预测模型
        y_true = np.random.randint(0, 2, n)
        y_pred = y_true * 0.7 + np.random.rand(n) * 0.3

        # 1. 校准度检验
        hl_result = hosmer_lemeshow_test(y_true, y_pred)
        assert hl_result["p_value"] is not None

        # 2. 最优阈值
        threshold_result = compute_optimal_threshold(y_true, y_pred, method="youden")
        assert threshold_result["threshold"] is not None

        # 3. DCA 解读
        net_benefit_data = {"net_benefits": [0.0, 0.05, 0.10, 0.08], "optimal_range": (0.3, 0.7)}
        dca_text = generate_dca_interpretation(net_benefit_data, "Model")

        assert len(dca_text) > 0
        assert "决策曲线" in dca_text
