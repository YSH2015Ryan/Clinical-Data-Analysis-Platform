"""插件管理 schemas（docs/14 ModelPlugin；/admin/plugins + /models）。"""

from typing import Any

from pydantic import BaseModel


class ModelPluginOut(BaseModel):
    key: str
    name: str
    version: str
    task_types: list[str]
    capability: dict[str, Any]
    enabled: bool


class PluginUpdate(BaseModel):
    """PATCH /admin/plugins/{key}：字段缺省即不更新。"""

    enabled: bool | None = None
    default_params: dict[str, Any] | None = None
