"""插件管理 schemas（docs/14 ModelPlugin；/admin/plugins + /models）。"""

from typing import Any, Literal

from pydantic import BaseModel


class ModelPluginOut(BaseModel):
    key: str
    name: str
    version: str
    task_types: list[str]
    capability: dict[str, Any]
    enabled: bool
    # T6.12 模型分层：standard=标准套餐（向导默认勾选），advanced=高级选项（折叠）
    tier: Literal["standard", "advanced"] = "advanced"
    role: str | None = None  # 标准套餐内角色标注（基线/强模型/可解释）


class PluginUpdate(BaseModel):
    """PATCH /admin/plugins/{key}：字段缺省即不更新。"""

    enabled: bool | None = None
    default_params: dict[str, Any] | None = None
