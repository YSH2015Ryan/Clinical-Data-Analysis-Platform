"""认证端点（冻结契约 docs/14 §3：POST /auth/login、POST /auth/refresh）。"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_token
from app.db import get_db
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

_auth_failed = AppError(code="AUTH_FAILED", status=401, message="认证失败")


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await auth_service.authenticate(db, body.email, body.password)
    if user is None:
        raise AppError(code="AUTH_FAILED", status=401, message="邮箱或密码错误")
    return auth_service.issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    claims = decode_token(body.refresh_token, expected="refresh")
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError):
        raise _auth_failed from None
    user = await auth_service.get_user(db, user_id)
    if user is None or not user.is_active:
        raise _auth_failed
    return auth_service.issue_tokens(user)
