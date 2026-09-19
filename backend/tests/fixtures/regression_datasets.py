"""回归测试数据集骨架（updateplan §86，Dataset A–J）。

每个生成器确定性地产出含「已知问题」的小型合成数据集，供回归测试
持续验证引擎能否发现这些问题（§80–81：验证引擎「诚实」）；
Dataset I 的 Ground Truth 验证见 ground_truth.py（§87：验证「算得对」）。

Dataset H 默认缩小规模供 CI 冒烟；需要全量压力测试时传 n=300_000。
已知问题清单锚定 §88（age=598 / 重复行 / 3.5% 阳性率 / month_group 泄漏）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_SEED = 86


def _base_df(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """公共骨架：patient_id + age + bmi + treatment + 二分类结局（logistic DGP）。"""
    age = rng.normal(60.0, 12.0, n)
    bmi = rng.normal(24.0, 4.0, n)
    treatment = rng.binomial(1, 0.5, n)
    logit = -2.0 + 0.03 * (age - 60.0) + 0.5 * treatment
    y = (rng.uniform(0.0, 1.0, n) < 1.0 / (1.0 + np.exp(-logit))).astype(int)
    return pd.DataFrame(
        {
            "patient_id": [f"P{i:06d}" for i in range(n)],
            "age": age,
            "bmi": bmi,
            "treatment": treatment,
            "outcome": y,
        }
    )


def make_dataset_a(n: int = 500) -> pd.DataFrame:
    """Dataset A：正常二分类（无已知问题，阴性对照）。"""
    return _base_df(n, np.random.default_rng(_SEED))


def make_dataset_b(n: int = 2000) -> pd.DataFrame:
    """Dataset B：严重类别不平衡（阳性率 ≈ 3.5%，锚定 §88）。"""
    rng = np.random.default_rng(_SEED + 1)
    df = _base_df(n, rng)
    logit = -5.4 + 0.02 * (df["age"] - 60.0) + 0.4 * df["treatment"]
    df["outcome"] = (rng.uniform(0.0, 1.0, n) < 1.0 / (1.0 + np.exp(-logit))).astype(int)
    return df


def make_dataset_c(n: int = 500) -> pd.DataFrame:
    """Dataset C：target leakage——month_group 由结局派生（泄漏列）。"""
    df = _base_df(n, np.random.default_rng(_SEED + 2))
    df["month_group"] = np.where(df["outcome"] == 1, "M9", "M1")
    return df


def make_dataset_d(n: int = 500, dup_frac: float = 0.15) -> pd.DataFrame:
    """Dataset D：patient duplicates——约 15% 行整行重复（同一患者重复录入）。"""
    df = _base_df(n, np.random.default_rng(_SEED + 3))
    dup_idx = np.random.default_rng(_SEED + 4).choice(n, size=int(n * dup_frac), replace=False)
    return pd.concat([df, df.iloc[dup_idx]], ignore_index=True)


def make_dataset_e(n: int = 500, n_outliers: int = 5) -> pd.DataFrame:
    """Dataset E：extreme outliers——age=598 等临床不可能值（锚定 §88）。"""
    df = _base_df(n, np.random.default_rng(_SEED + 5))
    df.loc[df.index[:n_outliers], "age"] = 598.0
    return df


def make_dataset_f(n: int = 500) -> pd.DataFrame:
    """Dataset F：temporal data——入院日期 + 随访月序号（时间结构）。"""
    df = _base_df(n, np.random.default_rng(_SEED + 6))
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    df["admission_date"] = dates.strftime("%Y-%m-%d")
    df["followup_month"] = (np.arange(n) % 12) + 1
    return df


def make_dataset_g(n: int = 500) -> pd.DataFrame:
    """Dataset G：survival data——time/event + 暴露（Cox 指数 DGP）。"""
    rng = np.random.default_rng(_SEED + 7)
    df = _base_df(n, rng).drop(columns=["outcome"])
    hazard = 0.02 * np.exp(0.5 * df["treatment"])
    t_event = rng.exponential(1.0 / hazard)
    t_cens = rng.exponential(60.0, n)
    df["time"] = np.minimum(t_event, t_cens)
    df["event"] = (t_event <= t_cens).astype(int)
    return df


def make_dataset_h(n: int = 2000) -> pd.DataFrame:
    """Dataset H：大行数骨架（§86 要求 300k；CI 默认缩小，压测传 n=300_000）。"""
    return _base_df(n, np.random.default_rng(_SEED + 8))


def make_dataset_i(n: int = 16000) -> tuple[pd.DataFrame, dict[str, float]]:
    """Dataset I：ground truth simulated dataset（详见 ground_truth.py / §87）。"""
    from tests.fixtures.ground_truth import make_binary_ground_truth

    return make_binary_ground_truth(n=n)


def make_dataset_j(n: int = 300, n_events: int = 40, n_features: int = 20) -> pd.DataFrame:
    """Dataset J：low EPV——事件数 40、预测变量 20 个（EPV=2 < 10）。"""
    rng = np.random.default_rng(_SEED + 10)
    df = pd.DataFrame({f"x{k:02d}": rng.normal(0.0, 1.0, n) for k in range(n_features)})
    df["patient_id"] = [f"P{i:06d}" for i in range(n)]
    # 强制恰好 n_events 个事件：按线性预测分排序取前 n_events
    score = df[[f"x{k:02d}" for k in range(5)]].sum(axis=1) + rng.normal(0, 0.5, n)
    df["outcome"] = 0
    df.loc[score.nlargest(n_events).index, "outcome"] = 1
    return df
