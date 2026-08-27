"""
报告增强 - 模型诊断模块

为回归模型提供统计检验和诊断分析。
"""

from typing import Any

import numpy as np
from scipy import stats
from scipy.stats import norm


def shapiro_wilk_test(residuals: np.ndarray) -> dict[str, Any]:
    """
    Shapiro-Wilk 正态性检验
    
    用于检验回归模型的残差是否服从正态分布。
    
    Args:
        residuals: 残差数组
        
    Returns:
        {
            "statistic": W 统计量,
            "p_value": p 值,
            "is_normal": 是否正态（p > 0.05）,
            "conclusion": 结论文本
        }
    """
    # 移除 NaN 和 Inf
    clean_residuals = residuals[np.isfinite(residuals)]
    
    if len(clean_residuals) < 3:
        return {
            "statistic": None,
            "p_value": None,
            "is_normal": None,
            "conclusion": "样本量不足，无法进行正态性检验"
        }
    
    # Shapiro-Wilk 检验（scipy 限制样本量 ≤5000）
    if len(clean_residuals) > 5000:
        # 大样本：使用 Kolmogorov-Smirnov 检验
        statistic, p_value = stats.kstest(
            (clean_residuals - clean_residuals.mean()) / clean_residuals.std(),
            'norm'
        )
        test_name = "Kolmogorov-Smirnov"
    else:
        statistic, p_value = stats.shapiro(clean_residuals)
        test_name = "Shapiro-Wilk"
    
    is_normal = p_value > 0.05
    
    if is_normal:
        conclusion = (
            f"残差通过{test_name}正态性检验（W={statistic:.4f}, p={p_value:.3f}），"
            "满足线性回归的正态性假设。"
        )
    else:
        conclusion = (
            f"残差未通过{test_name}正态性检验（W={statistic:.4f}, p={p_value:.3f}），"
            "提示可能存在非线性关系或异常值，建议检查模型设定或考虑变换因变量。"
        )
    
    return {
        "statistic": float(statistic),
        "p_value": float(p_value),
        "is_normal": is_normal,
        "conclusion": conclusion,
        "test_name": test_name
    }


def breusch_pagan_test(
    X: np.ndarray, 
    residuals: np.ndarray
) -> dict[str, Any]:
    """
    Breusch-Pagan 同方差性检验
    
    用于检验回归模型的残差方差是否恒定（同方差性）。
    
    Args:
        X: 自变量矩阵 (n_samples, n_features)
        residuals: 残差数组 (n_samples,)
        
    Returns:
        {
            "statistic": LM 统计量,
            "p_value": p 值,
            "is_homoscedastic": 是否同方差（p > 0.05）,
            "conclusion": 结论文本
        }
    """
    # 移除 NaN
    mask = np.isfinite(residuals) & np.all(np.isfinite(X), axis=1)
    X_clean = X[mask]
    residuals_clean = residuals[mask]
    
    n = len(residuals_clean)
    
    if n < 10 or X_clean.shape[1] == 0:
        return {
            "statistic": None,
            "p_value": None,
            "is_homoscedastic": None,
            "conclusion": "样本量不足或缺少自变量，无法进行同方差性检验"
        }
    
    # 计算残差平方
    residuals_sq = residuals_clean ** 2
    
    # 残差平方对自变量回归
    # 添加截距项
    X_with_intercept = np.column_stack([np.ones(n), X_clean])
    
    try:
        # OLS: (X'X)^{-1} X'y
        XtX_inv = np.linalg.inv(X_with_intercept.T @ X_with_intercept)
        beta = XtX_inv @ X_with_intercept.T @ residuals_sq
        
        # 预测值
        fitted = X_with_intercept @ beta
        
        # SSR (Sum of Squared Residuals)
        SSR = np.sum((fitted - residuals_sq.mean()) ** 2)
        
        # SST (Total Sum of Squares)
        SST = np.sum((residuals_sq - residuals_sq.mean()) ** 2)
        
        # R²
        r_squared = SSR / SST if SST > 0 else 0
        
        # LM 统计量 = n * R²
        lm_statistic = n * r_squared
        
        # 自由度 = 自变量个数
        df = X_clean.shape[1]
        
        # p 值（卡方分布）
        p_value = 1 - stats.chi2.cdf(lm_statistic, df)
        
    except np.linalg.LinAlgError:
        return {
            "statistic": None,
            "p_value": None,
            "is_homoscedastic": None,
            "conclusion": "矩阵奇异，无法进行同方差性检验（可能存在多重共线性）"
        }
    
    is_homoscedastic = p_value > 0.05
    
    if is_homoscedastic:
        conclusion = (
            f"残差通过Breusch-Pagan同方差性检验（LM={lm_statistic:.4f}, p={p_value:.3f}），"
            "满足线性回归的同方差性假设。"
        )
    else:
        conclusion = (
            f"残差未通过Breusch-Pagan同方差性检验（LM={lm_statistic:.4f}, p={p_value:.3f}），"
            "提示存在异方差性，建议使用稳健标准误或加权最小二乘法。"
        )
    
    return {
        "statistic": float(lm_statistic),
        "p_value": float(p_value),
        "is_homoscedastic": is_homoscedastic,
        "conclusion": conclusion
    }


def generate_diagnostic_paragraph(
    shapiro_result: dict[str, Any] | None = None,
    bp_result: dict[str, Any] | None = None
) -> str:
    """
    生成模型诊断段落
    
    将 Shapiro-Wilk 和 Breusch-Pagan 检验结果整合为学术段落。
    
    Args:
        shapiro_result: Shapiro-Wilk 检验结果
        bp_result: Breusch-Pagan 检验结果
        
    Returns:
        诊断段落文本
    """
    paragraphs = []
    
    # 标题
    paragraphs.append("**模型诊断**")
    paragraphs.append("")
    
    if shapiro_result and shapiro_result.get("p_value") is not None:
        paragraphs.append(shapiro_result["conclusion"])
    
    if bp_result and bp_result.get("p_value") is not None:
        paragraphs.append(bp_result["conclusion"])
    
    # 如果两个检验都通过
    if (shapiro_result and shapiro_result.get("is_normal") and
        bp_result and bp_result.get("is_homoscedastic")):
        paragraphs.append(
            "综合诊断结果表明，模型满足线性回归的基本假设，"
            "回归系数的显著性检验和置信区间有效。"
        )
    elif not paragraphs[2:]:  # 如果没有任何检验结果
        paragraphs.append("模型诊断检验未执行或样本量不足。")
    
    return "\n\n".join(paragraphs)


def durbin_watson_test(residuals: np.ndarray) -> dict[str, Any]:
    """
    Durbin-Watson 自相关检验
    
    用于检验残差是否存在自相关（常见于时间序列数据）。
    
    Args:
        residuals: 残差数组
        
    Returns:
        {
            "statistic": DW 统计量 (0-4),
            "conclusion": 结论文本
        }
    """
    clean_residuals = residuals[np.isfinite(residuals)]
    
    if len(clean_residuals) < 2:
        return {
            "statistic": None,
            "conclusion": "样本量不足，无法计算 Durbin-Watson 统计量"
        }
    
    # DW = Σ(e_t - e_{t-1})² / Σe_t²
    diff = np.diff(clean_residuals)
    dw_statistic = np.sum(diff ** 2) / np.sum(clean_residuals ** 2)
    
    # DW ≈ 2 表示无自相关
    # DW < 2 表示正自相关
    # DW > 2 表示负自相关
    
    if 1.5 <= dw_statistic <= 2.5:
        interpretation = "无显著自相关"
    elif dw_statistic < 1.5:
        interpretation = "存在正自相关，提示相邻观测值的残差相似"
    else:
        interpretation = "存在负自相关，提示相邻观测值的残差交替"
    
    conclusion = (
        f"Durbin-Watson统计量为{dw_statistic:.3f}，{interpretation}。"
        if dw_statistic is not None else "无法计算自相关统计量。"
    )
    
    return {
        "statistic": float(dw_statistic) if dw_statistic is not None else None,
        "conclusion": conclusion
    }


def vif_analysis(X: np.ndarray, feature_names: list[str] | None = None) -> dict[str, Any]:
    """
    方差膨胀因子 (VIF) 分析
    
    用于检测多重共线性。
    
    Args:
        X: 自变量矩阵 (n_samples, n_features)
        feature_names: 特征名称列表
        
    Returns:
        {
            "vif_values": {特征名: VIF值},
            "max_vif": 最大 VIF 值,
            "has_multicollinearity": 是否存在多重共线性 (VIF > 10),
            "conclusion": 结论文本
        }
    """
    n_features = X.shape[1]
    
    if feature_names is None:
        feature_names = [f"X{i+1}" for i in range(n_features)]
    
    if n_features < 2:
        return {
            "vif_values": {},
            "max_vif": None,
            "has_multicollinearity": False,
            "conclusion": "特征数量不足，无法计算 VIF"
        }
    
    vif_values = {}
    
    for i in range(n_features):
        # X_i 对其他 X 回归
        X_i = X[:, i]
        X_others = np.delete(X, i, axis=1)
        
        # 添加截距
        X_others_with_intercept = np.column_stack([np.ones(len(X_others)), X_others])
        
        try:
            # OLS
            XtX_inv = np.linalg.inv(X_others_with_intercept.T @ X_others_with_intercept)
            beta = XtX_inv @ X_others_with_intercept.T @ X_i
            fitted = X_others_with_intercept @ beta
            
            # R²
            ss_res = np.sum((X_i - fitted) ** 2)
            ss_tot = np.sum((X_i - X_i.mean()) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            # VIF = 1 / (1 - R²)
            vif = 1 / (1 - r_squared) if r_squared < 0.9999 else np.inf
            
        except (np.linalg.LinAlgError, ZeroDivisionError):
            vif = np.inf
        
        vif_values[feature_names[i]] = float(vif) if np.isfinite(vif) else None
    
    valid_vifs = [v for v in vif_values.values() if v is not None]
    max_vif = max(valid_vifs) if valid_vifs else None
    has_multicollinearity = max_vif > 10 if max_vif is not None else False
    
    if has_multicollinearity:
        conclusion = (
            f"检测到多重共线性（最大VIF={max_vif:.2f}），"
            "提示部分特征高度相关，可能影响回归系数的解释和稳定性。"
        )
    else:
        max_vif_str = f"{max_vif:.2f}" if max_vif is not None else "N/A"
        conclusion = f"VIF检验未发现严重多重共线性（最大VIF={max_vif_str}）。"
    
    return {
        "vif_values": vif_values,
        "max_vif": max_vif,
        "has_multicollinearity": has_multicollinearity,
        "conclusion": conclusion
    }
