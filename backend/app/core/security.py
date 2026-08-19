"""鉴权（docs/12 §2.2）：BCrypt 口令散列 + PyJWT 双 token（access 2h / refresh 7d）。

错误码与 docs/14 §2 冻结表一致：AUTH_FAILED / TOKEN_EXPIRED。
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.errors import AppError

TokenKind = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("密码 UTF-8 编码长度不能超过 72 字节")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if len(password.encode("utf-8")) > 72:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode())
    except ValueError:
        return False


def create_token(subject: str, role: str, kind: TokenKind) -> str:
    settings = get_settings()
    minutes = (
        settings.access_token_expire_minutes
        if kind == "access"
        else settings.refresh_token_expire_days * 24 * 60
    )
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "role": role,
        "type": kind,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected: TokenKind) -> dict[str, Any]:
    settings = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise AppError(code="TOKEN_EXPIRED", status=401, message="登录已过期，请重新登录") from None
    except jwt.InvalidTokenError:
        raise AppError(code="AUTH_FAILED", status=401, message="认证失败") from None
    if claims.get("type") != expected:
        raise AppError(code="AUTH_FAILED", status=401, message="认证失败")
    return claims


def token_hash(token: str) -> str:
    """只保存 refresh token 摘要，数据库泄露时不能直接重放会话。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
