"""排名与推荐理由模板引擎（docs/09 §4；docs/18 T6.3）。

score = w1×主指标归一化 + w2×稳定性归一化 + w3×次级指标归一化（默认 0.6/0.2/0.2）。

- 归一化：跨模型 min-max、方向感知（越低越好取反向）；全部并列时归一值取 1.0；
- 次级指标（校准/拟合优度）：classification=Brier、survival=IBS、regression=R²；
- 理由模板只引用真实计算的指标值；「最优/最稳定」等结论性措辞仅当对应分量
  存在跨模型差异且该模型取得最佳值时才出现（CLAUDE.md §8 结果真实）。
"""

from dataclasses import dataclass, field
from typing import Any, Literal

Direction = Literal["max", "min"]

_PRIMARY: dict[str, tuple[str, Direction]] = {
    "classification": ("auc", "max"),
    "survival": ("c_index", "max"),
    "regression": ("rmse", "min"),
}
_SECONDARY: dict[str, tuple[str, Direction]] = {
    "classification": ("brier", "min"),
    "survival": ("ibs", "min"),
    "regression": ("r2", "max"),
}

DEFAULT_WEIGHTS: dict[str, float] = {"primary": 0.6, "stability": 0.2, "secondary": 0.2}


@dataclass
class RankedModel:
    """单模型排名快照：综合得分 + 三个归一化分量 + 真实指标值。"""

    model_key: str
    score: float
    components: dict[str, float]
    primary_name: str
    primary_mean: float | None
    primary_std: float
    secondary_name: str
    secondary_mean: float | None
    rank: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


def _norm(values: list[float], direction: Direction) -> list[float]:
    """min-max 归一（方向感知）；全部并列 → 全 1.0。"""
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0] * len(values)
    span = hi - lo
    if direction == "max":
        return [(v - lo) / span for v in values]
    return [(hi - v) / span for v in values]


def _metric_mean(metrics: dict[str, Any], name: str) -> float | None:
    entry = metrics.get(name)
    if not isinstance(entry, dict) or entry.get("mean") is None:
        return None
    return float(entry["mean"])


def rank_models(
    task_type: str,
    rows: list[dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
) -> list[RankedModel]:
    """按综合得分降序排名；rows 为 [{"model_key", "metrics"}]（仅 SUCCESS 模型）。

    缺主指标的模型（如 dummy 基线只有 accuracy）不参与加权，按 model_key 排在末位，
    理由中如实说明（不虚构数值）。
    """
    if not rows:
        return []
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    primary_name, primary_dir = _PRIMARY[task_type]
    secondary_name, secondary_dir = _SECONDARY[task_type]

    means = [_metric_mean(r.get("metrics") or {}, primary_name) for r in rows]
    stds = [float((r.get("metrics") or {}).get(primary_name, {}).get("std", 0.0)) for r in rows]
    seconds = [_metric_mean(r.get("metrics") or {}, secondary_name) for r in rows]

    valid = [i for i, m in enumerate(means) if m is not None]
    primary_norm = (
        dict(zip(valid, _norm([m for m in means if m is not None], primary_dir), strict=True))
        if valid
        else {}
    )
    stability_norm = (
        dict(zip(valid, _norm([stds[i] for i in valid], "min"), strict=True)) if valid else {}
    )
    sec_pairs = [(i, s) for i, s in enumerate(seconds) if i in valid and s is not None]
    secondary_norm = (
        dict(
            zip(
                [i for i, _ in sec_pairs],
                _norm([s for _, s in sec_pairs], secondary_dir),
                strict=True,
            )
        )
        if sec_pairs
        else {}
    )

    ranked = []
    for i, row in enumerate(rows):
        mean_i = means[i]
        components = {
            "primary": round(primary_norm.get(i, 0.0), 6),
            "stability": round(stability_norm.get(i, 0.0), 6),
            "secondary": round(secondary_norm.get(i, 0.0), 6),
        }
        score = (
            w["primary"] * components["primary"]
            + w["stability"] * components["stability"]
            + w["secondary"] * components["secondary"]
        )
        ranked.append(
            RankedModel(
                model_key=row["model_key"],
                score=round(score, 6),
                components=components,
                primary_name=primary_name,
                primary_mean=mean_i,
                primary_std=stds[i],
                secondary_name=secondary_name,
                secondary_mean=seconds[i],
            )
        )
    # 缺主指标者沉底：先按是否缺主指标分组，再按得分/key 排序
    ranked.sort(key=lambda m: (m.primary_mean is None, -m.score, m.model_key))
    for idx, m in enumerate(ranked):
        m.rank = idx + 1
    return ranked


def _best_flags(ranked: list[RankedModel]) -> dict[str, bool]:
    """各分量是否存在跨模型差异（存在才允许「最优/最稳定」措辞）。

    只在参与加权评分的模型间比较（缺主指标的模型不构成「被超越」的证据）。
    """
    scored = [m for m in ranked if m.primary_mean is not None]
    return {
        key: len({m.components[key] for m in scored}) > 1
        for key in ("primary", "stability", "secondary")
    }


def _merit_clauses(m: RankedModel, varied: dict[str, bool]) -> list[str]:
    """领先优势条款：仅当分量有差异且该模型取得最佳归一值（1.0）时引用真实值。"""
    clauses = []
    if varied["secondary"] and m.components["secondary"] == 1.0 and m.secondary_mean is not None:
        clauses.append(f"校准/拟合优度最优（{m.secondary_name}={m.secondary_mean:.4f}）")
    if varied["stability"] and m.components["stability"] == 1.0:
        clauses.append(f"交叉验证最稳定（std={m.primary_std:.4f}）")
    return clauses


def _reason(m: RankedModel, ranked: list[RankedModel], varied: dict[str, bool]) -> str:
    if m.primary_mean is None:
        return f"缺少主指标 {m.primary_name}，未参与加权评分"
    head = f"{m.primary_name}={m.primary_mean:.4f}±{m.primary_std:.4f}"
    if m.rank == 1:
        parts = [f"主指标最高（{head}）", *_merit_clauses(m, varied)]
        return "，".join(parts)
    top = ranked[0]
    delta = abs((top.primary_mean or 0.0) - m.primary_mean)
    if m.rank == 2:
        parts = [f"主指标接近首位（{head}，差距 {delta:.4f}）", *_merit_clauses(m, varied)]
        return "，".join(parts)
    return f"综合得分第 {m.rank} 位（score={m.score:.4f}，{head}）"


def _not_recommended(ranked: list[RankedModel], varied: dict[str, bool]) -> list[dict[str, str]]:
    """末位模型的最弱分量（docs/09 §4.2）；无跨模型差异则不输出。"""
    if len(ranked) < 2:
        return []
    bottom = ranked[-1]
    if bottom.primary_mean is None:
        return [{"model_key": bottom.model_key, "reason": f"缺少主指标（{bottom.primary_name}）"}]
    weakest = min(bottom.components, key=lambda k: bottom.components[k])
    if not varied[weakest]:
        return []
    if weakest == "primary":
        reason = f"主指标最弱（{bottom.primary_name}={bottom.primary_mean:.4f}）"
    elif weakest == "stability":
        reason = f"交叉验证波动最大（std={bottom.primary_std:.4f}）"
    else:
        sec = bottom.secondary_mean
        reason = (
            f"校准/拟合优度最弱（{bottom.secondary_name}={sec:.4f}）"
            if sec is not None
            else f"缺少次级指标 {bottom.secondary_name}"
        )
    return [{"model_key": bottom.model_key, "reason": reason}]


def build_recommendation(
    task_type: str,
    rows: list[dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Comparison.recommendation 载荷（docs/04 §3；含排名公式披露）。"""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    ranked = rank_models(task_type, rows, weights=w)
    varied = _best_flags(ranked)
    return {
        "ranking": [m.model_key for m in ranked],
        "top": [
            {"model_key": m.model_key, "rank": m.rank, "reason": _reason(m, ranked, varied)}
            for m in ranked[:3]
        ],
        "not_recommended": _not_recommended(ranked, varied),
        "primary_metric": _PRIMARY[task_type][0],
        "formula": (
            f"score = {w['primary']}×主指标归一化 + {w['stability']}×稳定性归一化"
            f" + {w['secondary']}×次级指标归一化（docs/09 §4.1）"
        ),
        "scores": [
            {"model_key": m.model_key, "score": m.score, "components": m.components} for m in ranked
        ],
    }
