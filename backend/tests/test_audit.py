"""T1.4 审计日志埋点测试：登录成功/失败、项目创建/删除（docs/12 §5）。"""

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import AuditLog, User
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

EMAIL = "audit@example.com"
PASSWORD = "audit-pass"


@pytest.fixture()
async def researcher(db_session: AsyncSession) -> User:
    user = User(
        email=EMAIL, password_hash=hash_password(PASSWORD), role="researcher", display_name="A"
    )
    db_session.add(user)
    await db_session.commit()
    return user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


async def _actions(db: AsyncSession) -> list[str]:
    return list((await db.execute(select(AuditLog.action))).scalars().all())


class TestAuditTrail:
    async def test_login_success_recorded(
        self, client: AsyncClient, db_session: AsyncSession, researcher: User
    ) -> None:
        await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        rows = (
            (await db_session.execute(select(AuditLog).where(AuditLog.action == "auth.login")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].user_id == researcher.id

    async def test_login_failure_recorded(
        self, client: AsyncClient, db_session: AsyncSession, researcher: User
    ) -> None:
        await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong"})
        rows = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.action == "auth.login_failed")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].user_id is None
        assert rows[0].detail["email"] == EMAIL

    async def test_project_create_delete_recorded(
        self, client: AsyncClient, db_session: AsyncSession, researcher: User
    ) -> None:
        resp = await client.post(
            "/api/v1/projects", json={"name": "审计项目"}, headers=_auth(researcher)
        )
        project_id = resp.json()["id"]
        await client.delete(f"/api/v1/projects/{project_id}", headers=_auth(researcher))

        actions = await _actions(db_session)
        assert "project.create" in actions
        assert "project.delete" in actions

        row = (
            await db_session.execute(select(AuditLog).where(AuditLog.action == "project.delete"))
        ).scalar_one()
        assert row.user_id == researcher.id
        assert row.resource_type == "project"
        assert str(row.resource_id) == project_id

    async def test_failed_delete_not_recorded(
        self, client: AsyncClient, db_session: AsyncSession, researcher: User
    ) -> None:
        import uuid

        before = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
        await client.delete(f"/api/v1/projects/{uuid.uuid4()}", headers=_auth(researcher))
        after = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
        assert after == before
