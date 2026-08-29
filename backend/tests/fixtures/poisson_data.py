"""计数结局合成数据（tests/plugins/test_poisson.py 夹具）。

确定性种子生成：age 连续 + treatment 二值，结局为 Poisson 计数
（率由两协变量真实决定，便于率比方向可预期）。
"""

import numpy as np
import pandas as pd


def make_count_data(n: int = 240, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    age = rng.normal(60.0, 12.0, n)
    treatment = rng.binomial(1, 0.5, n).astype(float)
    mean = np.exp(0.5 + 0.02 * age + 0.4 * treatment)
    y = pd.Series(rng.poisson(mean), name="events")
    X = pd.DataFrame({"age": age, "treatment": treatment})
    return X, y
