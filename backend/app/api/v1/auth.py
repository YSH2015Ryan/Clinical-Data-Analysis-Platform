"""认证端点：HttpOnly Cookie 会话 + refresh rotation。"""

import hashlib
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decode_token, token_hash
from app.db import get_db
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse
from app.services import audit as audit_service
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

_auth_failed = AppError(code="AUTH_FAILED", status=401, message="认证失败")
_attempts: dict[str, deque[float]] = defaultdict(deque)


def _set_session_cookies(response: Response, tokens: TokenResponse) -> None:
    settings = get_settings()
    response.set_cookie(
        "cdap_access",
        tokens.access_token,
        max_age=settings.access_token_expire_minutes * 60,
        path="/api/v1",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        "cdap_refresh",
        tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 86400,
        path="/api/v1/auth",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie("cdap_access", path="/api/v1")
    response.delete_cookie("cdap_refresh", path="/api/v1/auth")


async def _check_login_rate_limit(request: Request, email: str) -> None:
    """按 IP+邮箱限流；Redis 可用时跨副本共享，故障时使用有界进程内兜底。"""
    settings = get_settings()
    host = request.client.host if request.client else "unknown"
    key = "cdap:login:" + hashlib.sha256(f"{host}:{email.lower()}".encode()).hexdigest()
    now = time.monotonic()
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
        count = int(await client.incr(key))
        if count == 1:
            await client.expire(key, settings.auth_rate_window_seconds)
        await client.aclose()
        if count > settings.auth_rate_limit:
            raise AppError("AUTH_RATE_LIMITED", 429, "登录尝试过于频繁，请稍后再试") from None
        return
    except AppError:
        raise
    except Exception:
        bucket = _attempts[key]
        cutoff = now - settings.auth_rate_window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(now)
        if len(bucket) > settings.auth_rate_limit:
            raise AppError("AUTH_RATE_LIMITED", 429, "登录尝试过于频繁，请稍后再试") from None


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    await _check_login_rate_limit(request, str(body.email))
    user = await auth_service.authenticate(db, body.email, body.password)
    if user is None:
        await audit_service.record(db, "auth.login_failed", detail={"email": body.email})
        await db.commit()
        raise AppError(code="AUTH_FAILED", status=401, message="邮箱或密码错误")
    await audit_service.record(db, "auth.login", user_id=user.id)
    tokens = await auth_service.issue_tokens(db, user)
    await db.commit()
    _set_session_cookies(response, tokens)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    refresh_token = (body.refresh_token if body else None) or request.cookies.get("cdap_refresh")
    if not refresh_token:
        raise _auth_failed
    claims = decode_token(refresh_token, expected="refresh")
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError):
        raise _auth_failed from None
    jti = str(claims.get("jti", ""))
    session = await auth_service.get_refresh_session(db, jti)
    user = await auth_service.get_user(db, user_id)
    if (
        session is None
        or session.user_id != user_id
        or session.revoked_at is not None
        or session.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
        or session.token_hash != token_hash(refresh_token)
        or user is None
        or not user.is_active
    ):
        raise _auth_failed
    tokens = await auth_service.issue_tokens(db, user, revoke_jti=jti)
    await db.commit()
    _set_session_cookies(response, tokens)
    return tokens


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await auth_service.revoke_refresh(db, request.cookies.get("cdap_refresh"))
    await db.commit()
    _clear_session_cookies(response)
    response.status_code = 204
    return response
