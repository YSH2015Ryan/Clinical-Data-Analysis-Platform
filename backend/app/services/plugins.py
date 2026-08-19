"""模型插件 DB 同步（docs/15 §1：enabled/default_params 以 DB 为准）。

启动/部署时调用：注册表中的插件 upsert 进 model_plugins 表——
新插件 enabled 默认 TRUE；已存在插件只更新元数据（name/version/task_types/
capability/default_params/entry_point），enabled 保留 DB 值（管理员禁用不被覆盖）。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.engines.model_registry import ModelRegistry
from app.models.entities import ModelPlugin


async def sync_plugins_to_db(db: AsyncSession, registry: ModelRegistry) -> int:
    """把注册表插件同步到 model_plugins；返回处理的插件数。"""
    count = 0
    for registered in registry.all():
        adapter = registered.adapter
        row = (
            await db.execute(select(ModelPlugin).where(ModelPlugin.key == adapter.key))
        ).scalar_one_or_none()
        if row is None:
            db.add(
                ModelPlugin(
                    key=adapter.key,
                    name=adapter.name,
                    version=adapter.version,
                    task_types=list(adapter.task_types),
                    capability=dict(adapter.capabilities),
                    default_params=dict(adapter.default_params),
                    enabled=True,
                    entry_point=registered.entry_point,
                )
            )
        else:
            row.name = adapter.name
            row.version = adapter.version
            row.task_types = list(adapter.task_types)
            row.capability = dict(adapter.capabilities)
            # 管理员配置是运行契约的一部分；注册表升级不能静默覆盖它。
            row.entry_point = registered.entry_point
            # enabled 保留 DB 值（docs/15 §1）
        count += 1
    return count


async def list_plugins(db: AsyncSession) -> list[ModelPlugin]:
    """全部插件（admin 管理页；docs/14 ModelPlugin）。"""
    return list((await db.execute(select(ModelPlugin).order_by(ModelPlugin.key))).scalars().all())


async def list_available(db: AsyncSession, task_type: str) -> list[ModelPlugin]:
    """启用且支持该任务类型的插件（GET /models；建模向导数据源）。"""
    rows = (
        (await db.execute(select(ModelPlugin).where(ModelPlugin.enabled.is_(True)))).scalars().all()
    )
    return [r for r in rows if task_type in r.task_types]


async def update_plugin(
    db: AsyncSession,
    key: str,
    *,
    enabled: bool | None = None,
    default_params: dict[str, Any] | None = None,
) -> ModelPlugin:
    """启用/禁用 + 默认参数更新（禁用即不可选：create_run PLUGIN_UNAVAILABLE 闸）。

    历史 run 不受影响：运行时已把 model_params 快照进 analysis_runs（docs/15 §1）。
    """
    row = (await db.execute(select(ModelPlugin).where(ModelPlugin.key == key))).scalar_one_or_none()
    if row is None:
        raise not_found("plugin", key)
    if enabled is not None:
        row.enabled = enabled
    if default_params is not None:
        row.default_params = dict(default_params)
    await db.flush()
    return row
