"""
报告增强 - 效应量分析和 DCA 增强

提供临床意义评估和决策曲线分析的详细解读。
"""

from typing import Any

import numpy as np
from scipy import stats


# MCID（最小临床重要差异）参考值
MCID_REFERENCE = {
    # 生活质量评分
    "sf36": 5.0,
    "eq5d": 0.074,
    # 疼痛评分
    "vas_pain": 10.0,  # 0-100 scale
    "nrs_pain": 1.5,   # 0-10 scale
    # 功能评分
    "barthel": 5.0,
    "fim": 22.0,
    # 实验室指标
    "hba1c": 0.5,      # %
    "ldl": 30.0,       # mg/dL
    "sbp": 5.0,        # mmHg
}


def cohens_d(
    group1: np.ndarray,
    group2: np.ndarray,
    pooled: bool = True
) -> dict[str, Any]:
    """
    计算 Cohen's d 效应量
    
    Args:
        group1: 组1数据
        group2: 组2数据
        pooled: 是否使用合并标准差（True）或仅用组1标准差（False）
        
    Returns:
        {
            "d": Cohen's d 值,
            "magnitude": 效应量级别,
            "interpretation": 解释文本,
            "mean_diff": 均值差异,
            "ci_lower": 95% CI 下限,
            "ci_upper": 95% CI 上限
        }
    """
    # 移除 NaN
    g1 = group1[np.isfinite(group1)]
    g2 = group2[np.isfinite(group2)]
    
    if len(g1) < 2 or len(g2) < 2:
        return {
            "d": None,
            "magnitude": None,
            "interpretation": "样本量不足，无法计算效应量",
            "mean_diff": None,
            "ci_lower": None,
            "ci_upper": None
        }
    
    # 均值和标准差
    mean1 = np.mean(g1)
    mean2 = np.mean(g2)
    std1 = np.std(g1, ddof=1)
    std2 = np.std(g2, ddof=1)
    
    mean_diff = mean1 - mean2
    
    # Cohen's d
    if pooled:
        # 合并标准差
        n1, n2 = len(g1), len(g2)
        pooled_std = np.sqrt(((n1 - 1) * std1**2 + (n2 - 1) * std2**2) / (n1 + n2 - 2))
        d = mean_diff / pooled_std if pooled_std > 0 else 0
    else:
        # 仅用组1标准差
        d = mean_diff / std1 if std1 > 0 else 0
    
    # 效应量级别（Cohen's convention）
    abs_d = abs(d)
    if abs_d < 0.2:
        magnitude = "negligible"
        magnitude_cn = "可忽略"
    elif abs_d < 0.5:
        magnitude = "small"
        magnitude_cn = "小"
    elif abs_d < 0.8:
        magnitude = "medium"
        magnitude_cn = "中等"
    else:
        magnitude = "large"
        magnitude_cn = "大"
    
    # 置信区间（近似）
    n1, n2 = len(g1), len(g2)
    se = np.sqrt((n1 + n2) / (n1 * n2) + d**2 / (2 * (n1 + n2)))
    ci_lower = d - 1.96 * se
    ci_upper = d + 1.96 * se
    
    interpretation = (
        f"Cohen's d = {d:.3f}（{magnitude_cn}效应量），"
        f"均值差异为 {mean_diff:.2f}，"
        f"95% CI [{ci_lower:.3f}, {ci_upper:.3f}]。"
    )
    
    return {
        "d": float(d),
        "magnitude": magnitude,
        "interpretation": interpretation,
        "mean_diff": float(mean_diff),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper)
    }


def compare_with_mcid(
    mean_diff: float,
    metric_name: str,
    custom_mcid: float | None = None
) -> dict[str, Any]:
    """
    比较效应量与 MCID
    
    Args:
        mean_diff: 均值差异
        metric_name: 指标名称
        custom_mcid: 自定义 MCID 值
        
    Returns:
        {
            "mcid": MCID 参考值,
            "ratio": 差异/MCID,
            "clinically_significant": 是否达到临床意义,
            "interpretation": 解释文本
        }
    """
    # 获取 MCID
    mcid = custom_mcid if custom_mcid is not None else MCID_REFERENCE.get(metric_name.lower())
    
    if mcid is None:
        return {
            "mcid": None,
            "ratio": None,
            "clinically_significant": None,
            "interpretation": f"指标 {metric_name} 无已知 MCID 参考值"
        }
    
    ratio = abs(mean_diff) / mcid
    clinically_significant = ratio >= 1.0
    
    if clinically_significant:
        interpretation = (
            f"均值差异（{abs(mean_diff):.2f}）超过 MCID（{mcid:.2f}），"
            f"达到临床重要差异（{ratio:.2f}倍MCID），具有临床意义。"
        )
    else:
        interpretation = (
            f"均值差异（{abs(mean_diff):.2f}）未达到 MCID（{mcid:.2f}），"
            f"仅为 {ratio:.2f}倍MCID，临床意义有限。"
        )
    
    return {
        "mcid": float(mcid),
        "ratio": float(ratio),
        "clinically_significant": clinically_significant,
        "interpretation": interpretation
    }


def hosmer_lemeshow_test(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_bins: int = 10
) -> dict[str, Any]:
    """
    Hosmer-Lemeshow 校准度检验
    
    用于评估分类模型的预测概率是否校准良好。
    
    Args:
        y_true: 真实标签（0/1）
        y_pred: 预测概率
        n_bins: 分组数
        
    Returns:
        {
            "statistic": χ² 统计量,
            "p_value": p 值,
            "n_bins": 实际分组数,
            "well_calibrated": 是否校准良好（p > 0.05）,
            "conclusion": 结论文本
        }
    """
    # 移除 NaN
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    y = y_true[mask]
    p = y_pred[mask]
    
    if len(y) < n_bins * 2:
        return {
            "statistic": None,
            "p_value": None,
            "n_bins": None,
            "well_calibrated": None,
            "conclusion": "样本量不足，无法进行Hosmer-Lemeshow检验"
        }
    
    # 按预测概率分组
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_indices = np.digitize(p, bin_edges[1:-1])
    
    # 计算每组的观察值和期望值
    observed = []
    expected = []
    
    for i in range(n_bins):
        mask_bin = (bin_indices == i)
        if mask_bin.sum() == 0:
            continue
        
        y_bin = y[mask_bin]
        p_bin = p[mask_bin]
        
        # 观察到的事件数
        observed_events = y_bin.sum()
        observed_non_events = len(y_bin) - observed_events
        
        # 期望的事件数
        expected_events = p_bin.sum()
        expected_non_events = len(p_bin) - expected_events
        
        observed.extend([observed_events, observed_non_events])
        expected.extend([expected_events, expected_non_events])
    
    observed = np.array(observed)
    expected = np.array(expected)
    
    # χ² 统计量
    # 避免除以0
    expected = np.where(expected == 0, 1e-10, expected)
    statistic = np.sum((observed - expected)**2 / expected)
    
    # 自由度 = 分组数 - 2
    actual_bins = len(observed) // 2
    df = actual_bins - 2
    
    if df <= 0:
        return {
            "statistic": None,
            "p_value": None,
            "n_bins": actual_bins,
            "well_calibrated": None,
            "conclusion": "分组不足，无法进行检验"
        }
    
    # p 值
    p_value = 1 - stats.chi2.cdf(statistic, df)
    
    well_calibrated = p_value > 0.05
    
    if well_calibrated:
        conclusion = (
            f"Hosmer-Lemeshow检验显示模型校准良好（χ²={statistic:.3f}, "
            f"df={df}, p={p_value:.3f}），预测概率与实际发生率一致。"
        )
    else:
        conclusion = (
            f"Hosmer-Lemeshow检验显示模型校准不佳（χ²={statistic:.3f}, "
            f"df={df}, p={p_value:.3f}），预测概率与实际发生率存在偏差。"
        )
    
    return {
        "statistic": float(statistic),
        "p_value": float(p_value),
        "n_bins": actual_bins,
        "df": df,
        "well_calibrated": well_calibrated,
        "conclusion": conclusion
    }


def compute_optimal_threshold(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    method: str = "youden"
) -> dict[str, Any]:
    """
    计算最优阈值
    
    Args:
        y_true: 真实标签
        y_pred: 预测概率
        method: 方法（"youden", "f1", "cost_sensitive"）
        
    Returns:
        {
            "threshold": 最优阈值,
            "sensitivity": 灵敏度,
            "specificity": 特异度,
            "method": 使用的方法,
            "interpretation": 解释文本
        }
    """
    from sklearn.metrics import roc_curve, precision_recall_curve, f1_score
    
    # 移除 NaN
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    y = y_true[mask]
    p = y_pred[mask]
    
    if len(y) < 10:
        return {
            "threshold": None,
            "sensitivity": None,
            "specificity": None,
            "method": method,
            "interpretation": "样本量不足"
        }
    
    if method == "youden":
        # Youden Index = Sensitivity + Specificity - 1
        fpr, tpr, thresholds = roc_curve(y, p)
        youden_index = tpr - fpr
        optimal_idx = np.argmax(youden_index)
        
        threshold = float(thresholds[optimal_idx])
        sensitivity = float(tpr[optimal_idx])
        specificity = float(1 - fpr[optimal_idx])
        
        interpretation = (
            f"Youden指数最优阈值为 {threshold:.3f}，"
            f"此时灵敏度={sensitivity:.3f}，特异度={specificity:.3f}。"
        )
    
    elif method == "f1":
        # F1-optimal
        precision, recall, thresholds = precision_recall_curve(y, p)
        f1_scores = 2 * (precision * recall) / (precision + recall + 1e-10)
        optimal_idx = np.argmax(f1_scores)
        
        threshold = float(thresholds[optimal_idx]) if optimal_idx < len(thresholds) else 0.5
        
        # 重新计算指标
        y_pred_binary = (p >= threshold).astype(int)
        from sklearn.metrics import confusion_matrix
        tn, fp, fn, tp = confusion_matrix(y, y_pred_binary).ravel()
        
        sensitivity = float(tp / (tp + fn)) if (tp + fn) > 0 else 0
        specificity = float(tn / (tn + fp)) if (tn + fp) > 0 else 0
        
        interpretation = (
            f"F1最优阈值为 {threshold:.3f}，"
            f"此时灵敏度={sensitivity:.3f}，特异度={specificity:.3f}。"
        )
    
    else:
        # 默认 0.5
        threshold = 0.5
        y_pred_binary = (p >= threshold).astype(int)
        from sklearn.metrics import confusion_matrix
        tn, fp, fn, tp = confusion_matrix(y, y_pred_binary).ravel()
        
        sensitivity = float(tp / (tp + fn)) if (tp + fn) > 0 else 0
        specificity = float(tn / (tn + fp)) if (tn + fp) > 0 else 0
        
        interpretation = f"默认阈值 {threshold:.3f}"
    
    return {
        "threshold": threshold,
        "sensitivity": sensitivity,
        "specificity": specificity,
        "method": method,
        "interpretation": interpretation
    }


def generate_dca_interpretation(
    net_benefit_data: dict[str, Any],
    model_name: str
) -> str:
    """
    生成 DCA（决策曲线分析）详细解读
    
    Args:
        net_benefit_data: 净收益数据
        model_name: 模型名称
        
    Returns:
        解读文本
    """
    if not net_benefit_data:
        return "无决策曲线数据"
    
    # 提取关键信息
    max_net_benefit = max(net_benefit_data.get("net_benefits", [0]))
    optimal_threshold_range = net_benefit_data.get("optimal_range", (0.2, 0.8))
    
    interpretation = (
        f"**决策曲线分析（DCA）**\n\n"
        f"模型 {model_name} 的决策曲线显示：\n\n"
        f"1. **最大净收益**: {max_net_benefit:.4f}，表明在最优阈值下，"
        f"使用该模型比「全部治疗」或「全部不治疗」策略能带来更高的临床净收益。\n\n"
        f"2. **推荐阈值范围**: {optimal_threshold_range[0]:.2f} - {optimal_threshold_range[1]:.2f}，"
        f"在此范围内模型的净收益为正，适合用于临床决策。\n\n"
        f"3. **临床应用建议**: 当治疗的危害/成本较低时，可选择较低阈值（提高灵敏度）；"
        f"当治疗有较大风险时，应选择较高阈值（提高特异度）。\n\n"
        f"DCA 曲线越高，说明模型在该阈值下的临床价值越大。"
    )
    
    return interpretation
