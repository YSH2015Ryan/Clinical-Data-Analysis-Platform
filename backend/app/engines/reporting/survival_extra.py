"""生存补充统计（P3；docs/10 §2 第 5 章模型性能的生存专属内容）。

- at_risk_table：KM 图配套的风险集人数表（各时间点的 at-risk / 累计事件）；
- median_risk_logrank：按推荐模型 OOF 风险中位数分高/低风险组的 log-rank 检验，
  为 KM 分层曲线提供统计学显著性依据（lifelines 真实计算，不虚构）。
"""

from typing import Any, Sequence

import numpy as np

_MIN_EVENTS_LOGRANK = 5  # 事件过少时 log-rank 检验无意义


def at_risk_table(
    times: Sequence[float],
    events: Sequence[int],
    *,
    points: Sequence[float] | None = None,
) -> dict[str, Any] | None:
    """各时间点风险集人数与累计事件数；points 缺省取时间分位点（0/25/50/75/100%）。"""
    t = np.asarray(times, dtype=float)
    e = np.asarray(events, dtype=float)
    if len(t) == 0 or len(t) != len(e):
        return None
    if points is None:
        pts = np.unique(np.quantile(t, [0.0, 0.25, 0.5, 0.75, 1.0]))
    else:
        pts = np.asarray(points, dtype=float)
    return {
        "times": [round(float(p), 4) for p in pts],
        "at_risk": [int((t >= p).sum()) for p in pts],
        "events_cum": [int(e[t <= p].sum()) for p in pts],
    }


def median_risk_logrank(
    times: Sequence[float],
    events: Sequence[int],
    risks: Sequence[float],
) -> dict[str, Any] | None:
    """OOF 风险中位分层 → 高/低风险组 log-rank 检验；组退化或事件过少 → None。"""
    t = np.asarray(times, dtype=float)
    e = np.asarray(events, dtype=float)
    r = np.asarray(risks, dtype=float)
    if not (len(t) == len(e) == len(r)) or len(t) < 10:
        return None
    if e.sum() < _MIN_EVENTS_LOGRANK:
        return None
    median = float(np.median(r))
    high = r > median
    low = ~high
    if high.sum() == 0 or low.sum() == 0:  # 全部相等 → 无法分层
        return None
    if e[high].sum() < 1 or e[low].sum() < 1:  # 任一组无事件 → 检验退化
        return None
    from lifelines.statistics import logrank_test

    result = logrank_test(t[high], t[low], event_observed_A=e[high], event_observed_B=e[low])
    return {
        "median_risk": round(median, 6),
        "n_high": int(high.sum()),
        "n_low": int(low.sum()),
        "statistic": round(float(result.test_statistic), 4),
        "p_value": float(result.p_value),
    }
