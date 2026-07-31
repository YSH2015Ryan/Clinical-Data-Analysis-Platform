"""FastAPI 依赖：当前用户解析 + RBAC（docs/12 §2.2）。

api 层不 import app.models（import-linter 强制），跨层只传 CurrentUser DTO。
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, forbidden
from app.core.security import decode_token
from app.db import get_db
from app.engines.model_registry import ModelRegistry
from app.schemas.auth import CurrentUser
from app.services import auth as auth_service

_bearer = HTTPBearer(auto_error=False)

_auth_failed = AppError(code="AUTH_FAILED", status=401, message="认证失败")


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if cred is None:
        raise _auth_failed
    claims = decode_token(cred.credentials, expected="access")
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError):
        raise _auth_failed from None
    user = await auth_service.get_user(db, user_id)
    if user is None or not user.is_active:
        raise _auth_failed
    return CurrentUser(id=user.id, email=str(user.email), role=user.role)


def require_role(
    *roles: str,
) -> Callable[[CurrentUser], Coroutine[Any, Any, CurrentUser]]:
    """RBAC：admin 放行一切；其余角色须在白名单内（docs/12 §2.2）。"""

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role != "admin" and user.role not in roles:
            raise forbidden()
        return user

    return checker


_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    """进程级注册表依赖（entry_points 扫描一次；与 worker 侧同一约定）。"""
    global _registry
    if _registry is None:
        registry = ModelRegistry()
        registry.load()
        _registry = registry
    return _registry
