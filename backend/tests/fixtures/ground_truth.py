"""Ground Truth 合成数据（updateplan §87 Dataset I，P1-15）。

已知真实效应量（true OR / true HR / true β）的模拟数据集，用于验证
统计引擎「算得对」：输出须收敛到真实效应，并与参考实现
（statsmodels / lifelines / scikit-learn）对拍（§87：相对误差 < 1%）。

与 §86 回归数据集（A–J，见 regression_datasets.py）互补：
后者验证引擎「诚实」（能否发现已知问题），本模块验证引擎「算得对」。

所有生成器确定性种子；与引擎内部随机种子纪律一致（CLAUDE.md 规范 6）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ------------------------------------------------------------- 二分类（true OR）

BINARY_TRUE_OR = 2.0  # 暴露 treatment 的真实 OR
BINARY_TRUE_BETA_AGE = 0.04  # 协变量 age 的真实 log-OR 系数
BINARY_INTERCEPT = -2.2  # 使基线阳性率 ≈ 12%（贴近临床不均衡场景）


def make_binary_ground_truth(
    n: int = 16000, seed: int = 87
) -> tuple[pd.DataFrame, dict[str, float]]:
    """logistic DGP：treatment（二值暴露，p=0.5）+ age（连续协变量，与暴露独立）。

    logit P(y=1) = -2.2 + log(2.0)·treatment + 0.04·(age-60)
    → true OR(treatment) = 2.0；暴露与协变量独立 → 未校正 OR 亦收敛到 2.0。
    """
    rng = np.random.default_rng(seed)
    age = rng.normal(60.0, 10.0, n)
    treatment = rng.binomial(1, 0.5, n)
    logit = BINARY_INTERCEPT + np.log(BINARY_TRUE_OR) * treatment + BINARY_TRUE_BETA_AGE * (
        age - 60.0
    )
    y = (rng.uniform(0.0, 1.0, n) < 1.0 / (1.0 + np.exp(-logit))).astype(int)
    df = pd.DataFrame({"age": age, "treatment": treatment, "outcome": y})
    truth = {
        "true_or": BINARY_TRUE_OR,
        "true_beta_age": BINARY_TRUE_BETA_AGE,
        "intercept": BINARY_INTERCEPT,
    }
    return df, truth


# ------------------------------------------------------------- 生存（true HR）

SURVIVAL_TRUE_HR = 1.8  # 暴露 treated 的真实 HR
SURVIVAL_TRUE_BETA_AGE = 0.03


def make_survival_ground_truth(
    n: int = 2000, seed: int = 87, event_rate: float = 0.7
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Cox 指数 DGP：baseline 恒定风险，log HR = log(1.8)·treated + 0.03·(age-65)。

    独立均匀删失调校至约 70% 事件率；true HR(treated) = 1.8。
    """
    rng = np.random.default_rng(seed)
    age = rng.normal(65.0, 10.0, n)
    treated = rng.binomial(1, 0.5, n)
    linear = np.log(SURVIVAL_TRUE_HR) * treated + SURVIVAL_TRUE_BETA_AGE * (age - 65.0)
    hazard = 0.02 * np.exp(linear)  # baseline hazard 0.02
    t_event = rng.exponential(1.0 / hazard)
    # 独立删失：分位点校准使事件率 ≈ event_rate
    t_cens = rng.exponential(1.0 / 0.02) * (1.0 - event_rate) / max(event_rate, 1e-6)
    time = np.minimum(t_event, t_cens)
    event = (t_event <= t_cens).astype(int)
    df = pd.DataFrame({"age": age, "treated": treated, "time": time, "event": event})
    truth = {"true_hr": SURVIVAL_TRUE_HR, "true_beta_age": SURVIVAL_TRUE_BETA_AGE}
    return df, truth


# ------------------------------------------------------------- 回归（true β）

REG_TRUE_BETA_DOSE = 1.5
REG_TRUE_BETA_WEIGHT = 0.3
REG_INTERCEPT = 10.0
REG_NOISE_SD = 5.0


def make_regression_ground_truth(
    n: int = 2000, seed: int = 87
) -> tuple[pd.DataFrame, dict[str, float]]:
    """线性 DGP：y = 10 + 1.5·dose + 0.3·(weight-70) + ε，ε ~ N(0, 5²)。

    dose 与 weight 独立 → 未校正 β 亦收敛到 1.5；n=2000 时 SE(β)≈0.011，
    相对误差 < 1% 在统计上稳定成立。
    """
    rng = np.random.default_rng(seed)
    weight = rng.normal(70.0, 15.0, n)
    dose = rng.uniform(10.0, 50.0, n)
    y = (
        REG_INTERCEPT
        + REG_TRUE_BETA_DOSE * dose
        + REG_TRUE_BETA_WEIGHT * (weight - 70.0)
        + rng.normal(0.0, REG_NOISE_SD, n)
    )
    df = pd.DataFrame({"weight": weight, "dose": dose, "y": y})
    truth = {
        "true_beta_dose": REG_TRUE_BETA_DOSE,
        "true_beta_weight": REG_TRUE_BETA_WEIGHT,
        "intercept": REG_INTERCEPT,
    }
    return df, truth


# ------------------------------------------------------------- 校准（true slope）

CALIBRATION_TRUE_SLOPE = 0.5  # 预测 logit 被放大 2 倍 → 校准斜率真值 1/2


def make_miscalibrated_probabilities(
    n: int = 20000, seed: int = 87
) -> tuple[np.ndarray, np.ndarray, float]:
    """结局由真实 logit L 生成，预测概率来自 2·L（过度自信的模型）。

    校准回归 y ~ logit(p_pred) 的真实斜率 = 1/2、截距 = 0；
    返回 (y, p_pred, true_slope)。
    """
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 1.0, n)
    logit = -0.3 + 1.2 * x
    y = (rng.uniform(0.0, 1.0, n) < 1.0 / (1.0 + np.exp(-logit))).astype(float)
    p_pred = 1.0 / (1.0 + np.exp(-2.0 * logit))
    return y, p_pred, CALIBRATION_TRUE_SLOPE
