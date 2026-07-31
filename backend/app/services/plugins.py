"""模型插件 DB 同步（docs/15 §1：enabled/default_params 以 DB 为准）。

启动/部署时调用：注册表中的插件 upsert 进 model_plugins 表——
新插件 enabled 默认 TRUE；已存在插件只更新元数据（name/version/task_types/
capability/default_params/entry_point），enabled 保留 DB 值（管理员禁用不被覆盖）。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
            row.default_params = dict(adapter.default_params)
            row.entry_point = registered.entry_point
            # enabled 保留 DB 值（docs/15 §1）
        count += 1
    return count
