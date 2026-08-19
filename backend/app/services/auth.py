"""认证服务：口令校验、token 签发、用户查询（api 层不接触 ORM —— 分层纪律）。"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_token, token_hash, verify_password
from app.models.entities import RefreshSession, User
from app.schemas.auth import TokenResponse


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    """校验邮箱+口令；用户不存在/停用/口令错误均返回 None（不泄露原因）。"""
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def issue_tokens(
    db: AsyncSession, user: User, *, revoke_jti: str | None = None
) -> TokenResponse:
    """签发短时 access + 可轮换 refresh，并持久化 refresh 会话。"""
    subject = str(user.id)
    access_token = create_token(subject, user.role, "access")
    refresh_token = create_token(subject, user.role, "refresh")
    claims = jwt.decode(
        refresh_token,
        options={"verify_signature": False, "verify_exp": False},
    )
    if revoke_jti:
        old = (
            await db.execute(
                select(RefreshSession).where(RefreshSession.jti == revoke_jti).with_for_update()
            )
        ).scalar_one_or_none()
        if old is not None and old.revoked_at is None:
            old.revoked_at = datetime.now(UTC)
            old.replaced_by_hash = token_hash(refresh_token)
    db.add(
        RefreshSession(
            user_id=user.id,
            jti=str(claims["jti"]),
            token_hash=token_hash(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_expire_days),
        )
    )
    await db.flush()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def get_refresh_session(db: AsyncSession, jti: str) -> RefreshSession | None:
    return (
        await db.execute(select(RefreshSession).where(RefreshSession.jti == jti).with_for_update())
    ).scalar_one_or_none()


async def revoke_refresh(db: AsyncSession, token: str | None) -> None:
    if not token:
        return
    from app.core.security import decode_token

    try:
        claims = decode_token(token, expected="refresh")
    except Exception:
        return
    jti = claims.get("jti")
    if not jti:
        return
    session = await get_refresh_session(db, str(jti))
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
