"""T1.1 API 集成测试：/auth/login /auth/refresh（冻结契约 docs/14 §3）。"""

import pytest
from app.core.security import hash_password
from app.models.entities import User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

EMAIL = "doc@example.com"
PASSWORD = "clinic-2026"


@pytest.fixture()
async def seeded_user(db_session: AsyncSession) -> User:
    user = User(
        email=EMAIL,
        password_hash=hash_password(PASSWORD),
        role="researcher",
        display_name="Dr. Test",
    )
    db_session.add(user)
    await db_session.commit()
    return user


class TestLogin:
    async def test_login_ok_returns_token_pair(
        self, client: AsyncClient, seeded_user: User
    ) -> None:
        resp = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"] and body["refresh_token"]

    async def test_login_wrong_password_401(self, client: AsyncClient, seeded_user: User) -> None:
        resp = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong"})
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_FAILED"

    async def test_login_unknown_email_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "x"}
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_FAILED"

    async def test_login_invalid_payload_400_rfc7807(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/login", json={"email": "not-an-email"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body
        assert body["details"]["errors"]


class TestRefresh:
    async def _login(self, client: AsyncClient) -> dict[str, str]:
        resp = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        return resp.json()  # type: ignore[no-any-return]

    async def test_refresh_ok(self, client: AsyncClient, seeded_user: User) -> None:
        tokens = await self._login(client)
        resp = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] and body["refresh_token"]

    async def test_refresh_with_access_token_401(
        self, client: AsyncClient, seeded_user: User
    ) -> None:
        tokens = await self._login(client)
        resp = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_FAILED"

    async def test_refresh_garbage_401(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_FAILED"
