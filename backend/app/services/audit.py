"""审计日志服务（docs/12 §5；docs/13 audit_logs 表）。

动作全集随里程碑扩充：auth.login / auth.login_failed / project.create / project.delete
（M2 补 analysis.submit，M3 补 report.export —— 各任务 DoD 挂接）。
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog


async def record(
    db: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """追加一条审计记录；随调用方事务提交，失败不阻断主流程外的语义。"""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail or {},
        )
    )
