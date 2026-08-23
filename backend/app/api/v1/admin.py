"""插件管理端点（docs/14 /admin/plugins、/models；docs/15 §1）。

GET /admin/plugins（admin）→ 全量列表（先同步注册表，新插件即可见）；
PATCH /admin/plugins/{key}（admin）→ 启用/禁用 + 默认参数；
GET /models?task_type=（登录用户）→ 启用且支持该任务类型的插件。
"""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_registry, require_role
from app.db import get_db
from app.engines.model_registry import ModelRegistry
from app.schemas.auth import CurrentUser
from app.schemas.plugin import ModelPluginOut, PluginUpdate
from app.services import audit as audit_service
from app.services import plugins as plugin_service

router = APIRouter(tags=["admin"])

TaskTypeQuery = Literal["survival", "classification", "regression", "time_series"]


def _out(row: object) -> ModelPluginOut:
    # capability 为自由对象：附带 default_params 供管理页回显（契约不含独立字段）
    capability = dict(row.capability)  # type: ignore[attr-defined]
    capability["default_params"] = dict(row.default_params)  # type: ignore[attr-defined]
    return ModelPluginOut(
        key=row.key,  # type: ignore[attr-defined]
        name=row.name,  # type: ignore[attr-defined]
        version=row.version,  # type: ignore[attr-defined]
        task_types=list(row.task_types),  # type: ignore[attr-defined]
        capability=capability,
        enabled=bool(row.enabled),  # type: ignore[attr-defined]
    )


@router.get("/admin/plugins", response_model=list[ModelPluginOut])
async def list_admin_plugins(
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> list[ModelPluginOut]:
    await plugin_service.sync_plugins_to_db(db, registry)  # 新注册插件立即可见
    await db.commit()
    return [_out(r) for r in await plugin_service.list_plugins(db)]


@router.patch("/admin/plugins/{key}", response_model=ModelPluginOut)
async def update_admin_plugin(
    key: str,
    body: PluginUpdate,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> ModelPluginOut:
    await plugin_service.sync_plugins_to_db(db, registry)  # 保证行存在（新部署先 PATCH 也可）
    row = await plugin_service.update_plugin(
        db, key, enabled=body.enabled, default_params=body.default_params
    )
    await audit_service.record(
        db,
        "admin.plugin_update",
        user_id=user.id,
        resource_type="model_plugin",
        resource_id=None,
        detail={"key": key, "enabled": body.enabled, "default_params": body.default_params},
    )
    await db.commit()
    return _out(row)


@router.get("/models", response_model=list[ModelPluginOut])
async def list_available_models(
    task_type: TaskTypeQuery,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> list[ModelPluginOut]:
    # 不能依赖管理员页面先访问：新数据库启动后向导必须立即能拿到插件。
    await plugin_service.sync_plugins_to_db(db, registry)
    await db.commit()
    return [_out(r) for r in await plugin_service.list_available(db, task_type)]
