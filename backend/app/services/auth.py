"""认证服务：口令校验、token 签发、用户查询（api 层不接触 ORM —— 分层纪律）。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_token, verify_password
from app.models.entities import User
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


def issue_tokens(user: User) -> TokenResponse:
    subject = str(user.id)
    return TokenResponse(
        access_token=create_token(subject, user.role, "access"),
        refresh_token=create_token(subject, user.role, "refresh"),
    )
