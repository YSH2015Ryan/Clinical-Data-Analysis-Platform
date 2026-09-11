"""
报告增强 - 统计推断模块

为模型比较提供统计显著性检验。
"""

from typing import Any

import numpy as np
from scipy import stats


def paired_t_test(
    metric1: np.ndarray[Any, Any], metric2: np.ndarray[Any, Any], alternative: str = "two-sided"
) -> dict[str, Any]:
    """
    配对 t 检验

    用于比较两个模型在同一折交叉验证下的性能差异。

    Args:
        metric1: 模型1的指标数组（各折）
        metric2: 模型2的指标数组（各折）
        alternative: 备择假设（"two-sided", "less", "greater"）

    Returns:
        {
            "statistic": t 统计量,
            "p_value": p 值,
            "mean_diff": 平均差异,
            "ci_lower": 95% CI 下限,
            "ci_upper": 95% CI 上限,
            "significant": 是否显著（p < 0.05）,
            "conclusion": 结论文本
        }
    """
    # 移除 NaN
    mask = np.isfinite(metric1) & np.isfinite(metric2)
    m1 = metric1[mask]
    m2 = metric2[mask]

    if len(m1) < 2:
        return {
            "statistic": None,
            "p_value": None,
            "mean_diff": None,
            "ci_lower": None,
            "ci_upper": None,
            "significant": None,
            "conclusion": "样本量不足，无法进行配对t检验",
        }

    # 配对差异
    diff = m1 - m2
    mean_diff = float(np.mean(diff))

    # t 检验（零方差差异 → t 统计量退化：按确定性结论处理，避免 nan 流入报告）
    if float(np.std(diff, ddof=1)) == 0.0:
        if mean_diff == 0.0:
            statistic, p_value = 0.0, 1.0
        else:
            statistic = float("inf") if mean_diff > 0 else float("-inf")
            p_value = 0.0
        ci = (mean_diff, mean_diff)
    else:
        statistic, p_value = stats.ttest_rel(m1, m2, alternative=alternative)
        # 95% 置信区间
        se = stats.sem(diff)
        ci = stats.t.interval(0.95, len(diff) - 1, loc=mean_diff, scale=se)

    significant = bool(p_value < 0.05)

    if alternative == "two-sided":
        if significant:
            if mean_diff > 0:
                conclusion = f"模型1显著优于模型2（平均差异 {mean_diff:.4f}, p={p_value:.3f}）"
            else:
                conclusion = f"模型2显著优于模型1（平均差异 {abs(mean_diff):.4f}, p={p_value:.3f}）"
        else:
            conclusion = f"两个模型无显著差异（p={p_value:.3f}）"
    else:
        conclusion = f"t={statistic:.3f}, p={p_value:.3f}"

    return {
        "statistic": float(statistic),
        "p_value": float(p_value),
        "mean_diff": mean_diff,
        "ci_lower": float(ci[0]),
        "ci_upper": float(ci[1]),
        "significant": significant,
        "conclusion": conclusion,
    }


def delong_test(
    y_true: np.ndarray[Any, Any], y_score1: np.ndarray[Any, Any], y_score2: np.ndarray[Any, Any]
) -> dict[str, Any]:
    """
    DeLong 检验

    用于比较两个分类模型的 ROC AUC 是否有显著差异。

    Args:
        y_true: 真实标签（0/1）
        y_score1: 模型1的预测概率
        y_score2: 模型2的预测概率

    Returns:
        {
            "auc1": 模型1的AUC,
            "auc2": 模型2的AUC,
            "auc_diff": AUC差异,
            "z_statistic": z统计量,
            "p_value": p值,
            "significant": 是否显著,
            "conclusion": 结论文本
        }
    """
    from sklearn.metrics import roc_auc_score

    # 移除 NaN
    mask = np.isfinite(y_true) & np.isfinite(y_score1) & np.isfinite(y_score2)
    y = y_true[mask]
    s1 = y_score1[mask]
    s2 = y_score2[mask]

    if len(y) < 10:
        return {
            "auc1": None,
            "auc2": None,
            "auc_diff": None,
            "z_statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": "样本量不足，无法进行DeLong检验",
        }

    # 计算 AUC
    try:
        auc1 = roc_auc_score(y, s1)
        auc2 = roc_auc_score(y, s2)
    except ValueError:
        return {
            "auc1": None,
            "auc2": None,
            "auc_diff": None,
            "z_statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": "无法计算AUC（可能只有单一类别）",
        }

    auc_diff = auc1 - auc2

    # DeLong 检验（简化实现：使用正态近似）
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))

    if n_pos == 0 or n_neg == 0:
        return {
            "auc1": auc1,
            "auc2": auc2,
            "auc_diff": auc_diff,
            "z_statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": "只有单一类别，无法进行检验",
        }

    # 简化方差估计（Hanley & McNeil）
    q1 = auc1 / (2 - auc1)
    q2 = 2 * auc1**2 / (1 + auc1)
    se1_sq = (auc1 * (1 - auc1) + (n_pos - 1) * (q1 - auc1**2) + (n_neg - 1) * (q2 - auc1**2)) / (
        n_pos * n_neg
    )

    q1 = auc2 / (2 - auc2)
    q2 = 2 * auc2**2 / (1 + auc2)
    se2_sq = (auc2 * (1 - auc2) + (n_pos - 1) * (q1 - auc2**2) + (n_neg - 1) * (q2 - auc2**2)) / (
        n_pos * n_neg
    )

    # 假设协方差为 0（简化）
    se_diff = np.sqrt(se1_sq + se2_sq)

    # z 统计量
    z_statistic = auc_diff / se_diff if se_diff > 0 else 0

    # p 值（双侧）
    p_value = 2 * (1 - stats.norm.cdf(abs(z_statistic)))

    significant = bool(p_value < 0.05)

    if significant:
        if auc_diff > 0:
            conclusion = f"模型1的AUC显著高于模型2（{auc1:.3f} vs {auc2:.3f}, p={p_value:.3f}）"
        else:
            conclusion = f"模型2的AUC显著高于模型1（{auc2:.3f} vs {auc1:.3f}, p={p_value:.3f}）"
    else:
        conclusion = f"两个模型的AUC无显著差异（{auc1:.3f} vs {auc2:.3f}, p={p_value:.3f}）"

    return {
        "auc1": float(auc1),
        "auc2": float(auc2),
        "auc_diff": float(auc_diff),
        "z_statistic": float(z_statistic),
        "p_value": float(p_value),
        "significant": significant,
        "conclusion": conclusion,
    }


def friedman_test(*metrics: np.ndarray[Any, Any]) -> dict[str, Any]:
    """
    Friedman 检验

    用于比较多个模型（≥3个）在多个数据集/折上的性能差异。

    Args:
        *metrics: 每个模型的指标数组（各折），至少3个

    Returns:
        {
            "statistic": χ² 统计量,
            "p_value": p 值,
            "significant": 是否显著（p < 0.05）,
            "conclusion": 结论文本
        }
    """
    if len(metrics) < 3:
        return {
            "statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": "至少需要3个模型才能进行Friedman检验",
        }

    # 构造数据矩阵（行=折，列=模型）
    data: list[Any] = []
    min_len = min(len(m) for m in metrics)

    for i in range(min_len):
        row = [m[i] for m in metrics]
        if all(np.isfinite(row)):
            data.append(row)

    if len(data) < 2:
        return {
            "statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": "有效样本不足，无法进行Friedman检验",
        }

    data_matrix = np.array(data)

    # Friedman 检验
    statistic, p_value = stats.friedmanchisquare(*data_matrix.T)

    significant = bool(p_value < 0.05)

    if significant:
        conclusion = f"模型间存在显著差异（χ²={statistic:.3f}, p={p_value:.3f}），需进一步事后检验"
    else:
        conclusion = f"模型间无显著差异（χ²={statistic:.3f}, p={p_value:.3f}）"

    return {
        "statistic": float(statistic),
        "p_value": float(p_value),
        "significant": significant,
        "conclusion": conclusion,
        "n_models": len(metrics),
        "n_folds": len(data),
    }


def wilcoxon_signed_rank_test(
    metric1: np.ndarray[Any, Any], metric2: np.ndarray[Any, Any], alternative: str = "two-sided"
) -> dict[str, Any]:
    """
    Wilcoxon 符号秩检验（非参数版本的配对t检验）

    用于比较两个模型，当数据不满足正态分布假设时使用。

    Args:
        metric1: 模型1的指标数组
        metric2: 模型2的指标数组
        alternative: 备择假设

    Returns:
        检验结果
    """
    # 移除 NaN
    mask = np.isfinite(metric1) & np.isfinite(metric2)
    m1 = metric1[mask]
    m2 = metric2[mask]

    if len(m1) < 5:
        return {
            "statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": "样本量不足（需≥5），无法进行Wilcoxon检验",
        }

    # Wilcoxon 检验
    try:
        result = stats.wilcoxon(m1, m2, alternative=alternative)
        statistic = result.statistic
        p_value = result.pvalue
    except ValueError as e:
        return {
            "statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": f"无法进行检验：{e!s}",
        }

    significant = bool(p_value < 0.05)

    median_diff = float(np.median(m1 - m2))

    if significant:
        if median_diff > 0:
            conclusion = f"模型1显著优于模型2（中位数差异 {median_diff:.4f}, p={p_value:.3f}）"
        else:
            conclusion = f"模型2显著优于模型1（中位数差异 {abs(median_diff):.4f}, p={p_value:.3f}）"
    else:
        conclusion = f"两个模型无显著差异（p={p_value:.3f}）"

    return {
        "statistic": float(statistic),
        "p_value": float(p_value),
        "median_diff": median_diff,
        "significant": significant,
        "conclusion": conclusion,
    }


def mcnemar_test(
    y_true: np.ndarray[Any, Any], y_pred1: np.ndarray[Any, Any], y_pred2: np.ndarray[Any, Any]
) -> dict[str, Any]:
    """
    McNemar 检验

    用于比较两个分类模型的错误率是否有显著差异。

    Args:
        y_true: 真实标签
        y_pred1: 模型1的预测标签
        y_pred2: 模型2的预测标签

    Returns:
        检验结果
    """
    # 移除 NaN
    mask = np.isfinite(y_true) & np.isfinite(y_pred1) & np.isfinite(y_pred2)
    y = y_true[mask]
    p1 = y_pred1[mask]
    p2 = y_pred2[mask]

    if len(y) < 10:
        return {
            "statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": "样本量不足，无法进行McNemar检验",
        }

    # 构造列联表
    # n01: 模型1错误但模型2正确
    # n10: 模型1正确但模型2错误
    n01 = int(np.sum((p1 != y) & (p2 == y)))
    n10 = int(np.sum((p1 == y) & (p2 != y)))

    if n01 + n10 == 0:
        return {
            "statistic": None,
            "p_value": None,
            "significant": None,
            "conclusion": "两个模型的错误完全一致，无法检验",
        }

    # McNemar 统计量
    statistic = (abs(n01 - n10) - 1) ** 2 / (n01 + n10)

    # p 值（卡方分布，df=1）
    p_value = 1 - stats.chi2.cdf(statistic, 1)

    significant = bool(p_value < 0.05)

    if significant:
        if n10 > n01:
            conclusion = f"模型1显著优于模型2（χ²={statistic:.3f}, p={p_value:.3f}）"
        else:
            conclusion = f"模型2显著优于模型1（χ²={statistic:.3f}, p={p_value:.3f}）"
    else:
        conclusion = f"两个模型无显著差异（χ²={statistic:.3f}, p={p_value:.3f}）"

    return {
        "statistic": float(statistic),
        "p_value": float(p_value),
        "n01": n01,
        "n10": n10,
        "significant": significant,
        "conclusion": conclusion,
    }
