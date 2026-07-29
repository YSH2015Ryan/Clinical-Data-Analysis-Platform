"""T1.1 单元测试：BCrypt 散列 + JWT 双 token（docs/19；错误码 docs/14 §2）。"""

import pytest
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPassword:
    def test_hash_roundtrip(self) -> None:
        hashed = hash_password("s3cret!")
        assert hashed != "s3cret!"
        assert hashed.startswith("$2")  # BCrypt 标识
        assert verify_password("s3cret!", hashed)

    def test_wrong_password(self) -> None:
        assert not verify_password("wrong", hash_password("right"))


class TestToken:
    def test_access_roundtrip(self) -> None:
        token = create_token("user-1", "researcher", "access")
        claims = decode_token(token, expected="access")
        assert claims["sub"] == "user-1"
        assert claims["role"] == "researcher"
        assert claims["type"] == "access"

    def test_refresh_roundtrip(self) -> None:
        token = create_token("user-1", "viewer", "refresh")
        claims = decode_token(token, expected="refresh")
        assert claims["type"] == "refresh"

    def test_expired_token_raises_token_expired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
        token = create_token("user-1", "researcher", "access")
        with pytest.raises(AppError) as exc_info:
            decode_token(token, expected="access")
        assert exc_info.value.code == "TOKEN_EXPIRED"
        assert exc_info.value.status == 401

    def test_wrong_kind_raises_auth_failed(self) -> None:
        refresh = create_token("user-1", "researcher", "refresh")
        with pytest.raises(AppError) as exc_info:
            decode_token(refresh, expected="access")
        assert exc_info.value.code == "AUTH_FAILED"

    def test_garbage_token_raises_auth_failed(self) -> None:
        with pytest.raises(AppError) as exc_info:
            decode_token("not-a-jwt", expected="access")
        assert exc_info.value.code == "AUTH_FAILED"

    def test_wrong_secret_raises_auth_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = create_token("user-1", "researcher", "access")
        monkeypatch.setattr(get_settings(), "jwt_secret", "other-secret")
        with pytest.raises(AppError) as exc_info:
            decode_token(token, expected="access")
        assert exc_info.value.code == "AUTH_FAILED"
