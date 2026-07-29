"""T1.2/T1.3 集成测试：项目 CRUD + RBAC + 项目级隔离（docs/12 §2.2，契约 docs/14）。"""

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _auth(user: User) -> dict[str, str]:
    token = create_token(str(user.id), user.role, "access")
    return {"Authorization": f"Bearer {token}"}


async def _mkuser(db: AsyncSession, email: str, role: str) -> User:
    user = User(email=email, password_hash=hash_password("pass-123"), role=role, display_name=email)
    db.add(user)
    await db.commit()
    return user


@pytest.fixture()
async def researcher(db_session: AsyncSession) -> User:
    return await _mkuser(db_session, "r1@example.com", "researcher")


@pytest.fixture()
async def other_researcher(db_session: AsyncSession) -> User:
    return await _mkuser(db_session, "r2@example.com", "researcher")


@pytest.fixture()
async def viewer(db_session: AsyncSession) -> User:
    return await _mkuser(db_session, "v1@example.com", "viewer")


@pytest.fixture()
async def admin(db_session: AsyncSession) -> User:
    return await _mkuser(db_session, "admin@example.com", "admin")


class TestProjectCRUD:
    async def test_unauthenticated_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_FAILED"

    async def test_create_list_delete_flow(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.post(
            "/api/v1/projects",
            json={"name": "心衰队列", "description": "HF 2026"},
            headers=_auth(researcher),
        )
        assert resp.status_code == 201
        project = resp.json()
        assert project["name"] == "心衰队列"

        resp = await client.get("/api/v1/projects", headers=_auth(researcher))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert [p["id"] for p in items] == [project["id"]]

        resp = await client.delete(f"/api/v1/projects/{project['id']}", headers=_auth(researcher))
        assert resp.status_code == 204

        resp = await client.get("/api/v1/projects", headers=_auth(researcher))
        assert resp.json()["items"] == []

    async def test_create_validation_error_400(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.post("/api/v1/projects", json={}, headers=_auth(researcher))
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"


class TestRBAC:
    async def test_viewer_create_403(self, client: AsyncClient, viewer: User) -> None:
        resp = await client.post("/api/v1/projects", json={"name": "x"}, headers=_auth(viewer))
        assert resp.status_code == 403
        assert resp.json()["code"] == "FORBIDDEN"

    async def test_viewer_delete_403(
        self, client: AsyncClient, viewer: User, researcher: User
    ) -> None:
        resp = await client.post("/api/v1/projects", json={"name": "x"}, headers=_auth(researcher))
        project_id = resp.json()["id"]
        resp = await client.delete(f"/api/v1/projects/{project_id}", headers=_auth(viewer))
        assert resp.status_code == 403

    async def test_viewer_can_list_own(self, client: AsyncClient, viewer: User) -> None:
        resp = await client.get("/api/v1/projects", headers=_auth(viewer))
        assert resp.status_code == 200
        assert resp.json()["items"] == []


class TestProjectIsolation:
    async def test_cross_owner_list_invisible(
        self, client: AsyncClient, researcher: User, other_researcher: User
    ) -> None:
        await client.post("/api/v1/projects", json={"name": "A 的项目"}, headers=_auth(researcher))
        resp = await client.get("/api/v1/projects", headers=_auth(other_researcher))
        assert resp.json()["items"] == []

    async def test_cross_owner_delete_404(
        self, client: AsyncClient, researcher: User, other_researcher: User
    ) -> None:
        resp = await client.post(
            "/api/v1/projects", json={"name": "A 的项目"}, headers=_auth(researcher)
        )
        project_id = resp.json()["id"]
        resp = await client.delete(
            f"/api/v1/projects/{project_id}", headers=_auth(other_researcher)
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "PROJECT_NOT_FOUND"

    async def test_admin_can_delete_any(
        self, client: AsyncClient, researcher: User, admin: User
    ) -> None:
        resp = await client.post(
            "/api/v1/projects", json={"name": "A 的项目"}, headers=_auth(researcher)
        )
        project_id = resp.json()["id"]
        resp = await client.delete(f"/api/v1/projects/{project_id}", headers=_auth(admin))
        assert resp.status_code == 204
