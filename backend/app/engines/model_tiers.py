"""模型分层套餐（tasks/phase6 T6.12）：每任务"标准套餐"3–5 个，其余为高级选项。

- 套餐构成：基线 + 强模型 + 可解释模型；与 T6.9 科研模板推荐模型保持一致；
- 分层是展示/默认选择策略（向导默认勾选标准套餐），不影响训练与比较引擎；
- tier 与任务类型相关（同一插件在不同任务下分层可不同，如 gam）。

分层纪律：纯引擎，只依赖标准库；禁止 import fastapi/celery/sqlalchemy。
"""

from typing import Literal

Tier = Literal["standard", "advanced"]

# 标准套餐（3–5 个/任务：基线 + 强模型 + 可解释模型）
STANDARD_PACKAGES: dict[str, tuple[str, ...]] = {
    "classification": ("logreg", "rf", "xgboost"),
    "regression": ("lasso", "rf_reg", "gam", "xgboost_reg"),
    "survival": ("coxph", "rsf", "gbs"),
}

# 套餐内模型的角色标注（前端展示「为什么默认选它」）
MODEL_ROLES: dict[str, str] = {
    "logreg": "基线 · 可解释",
    "rf": "强模型 · 可解释",
    "xgboost": "强模型",
    "lasso": "基线 · 可解释",
    "rf_reg": "强模型 · 可解释",
    "gam": "可解释 · 非线性",
    "xgboost_reg": "强模型",
    "coxph": "基线 · 可解释",
    "rsf": "强模型 · 可解释",
    "gbs": "强模型",
}


def tier_of(task_type: str, model_key: str) -> Tier:
    """模型在指定任务下的分层：套餐内 standard，其余（含未知任务类型）advanced。"""
    if model_key in STANDARD_PACKAGES.get(task_type, ()):
        return "standard"
    return "advanced"


def role_of(model_key: str) -> str | None:
    """标准套餐内模型的角色标注；高级选项无标注（None）。"""
    return MODEL_ROLES.get(model_key)
