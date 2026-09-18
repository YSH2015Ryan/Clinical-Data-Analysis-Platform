"""P1-13 多重比较校正（updateplan §30）。

批量单变量检验（同一结局对 N 个变量分别检验）的未校正 p 值系统性虚低。
默认 Benjamini–Hochberg（FDR）；可切换 Bonferroni；选择「不校正」时
调用方必须展示警告（correction_warning，见 screening.py）。

校正算法调用 statsmodels multipletests，不重新实现（CLAUDE.md 规范 2）。
分层纪律：engines 禁止 import fastapi/celery/sqlalchemy。
"""

from __future__ import annotations

import numpy as np
from statsmodels.stats.multitest import multipletests

CORRECTION_METHODS = ("bh", "bonferroni", "none")

_METHOD_LABELS = {"bh": "Benjamini–Hochberg(FDR)", "bonferroni": "Bonferroni", "none": "不校正"}

# §30：选择「不校正」时必须显示的警告（固定文案）
NO_CORRECTION_WARNING = (
    "未进行多重比较校正：批量检验的假阳性率随检验数量上升，"
    "显著性结论仅供参考，建议切换 Benjamini–Hochberg 或 Bonferroni 校正。"
)


def correction_label(method: str) -> str:
    return _METHOD_LABELS[method]


def adjust_pvalues(
    pvalues: list[float | None], *, method: str = "bh"
) -> list[float | None]:
    """对 p 值列表做多重比较校正；None（不可估计）保持 None 且不计入检验总数。

    Raises:
        ValueError: method 不在 bh / bonferroni / none 之内。
    """
    if method not in CORRECTION_METHODS:
        raise ValueError(f"未知校正方法 {method}，可选：{'/'.join(CORRECTION_METHODS)}")
    if method == "none":
        return list(pvalues)
    valid_idx = [i for i, p in enumerate(pvalues) if p is not None]
    adjusted: list[float | None] = list(pvalues)
    if not valid_idx:
        return adjusted
    raw = np.array([pvalues[i] for i in valid_idx], dtype=float)
    sm_method = "fdr_bh" if method == "bh" else "bonferroni"
    corrected = multipletests(raw, method=sm_method)[1]
    for i, idx in enumerate(valid_idx):
        adjusted[idx] = float(corrected[i])
    return adjusted
