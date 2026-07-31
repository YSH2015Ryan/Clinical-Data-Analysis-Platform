"""T4.2 detect-task 端点测试：识别成功 200 + 失败 422 + 隔离 404（docs/14 §3）。"""

import io

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, Project, User
from app.services.storage import storage_from_settings
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

SURVIVAL_CSV = (
    "age,os_months,death\n" + "\n".join(f"{40 + i},{6 + i},{i % 2}" for i in range(20))
).encode("utf-8")

NO_TARGET_CSV = ("x1,x2\n" + "\n".join(f"{i}.5,{i * 2}.5" for i in range(20))).encode("utf-8")


@pytest.fixture()
async def user(db_session: AsyncSession) -> tuple[Project, User]:
    u = User(
        email="td@example.com",
        password_hash=hash_password("td-pass"),
        role="researcher",
        display_name="TD",
    )
    db_session.add(u)
    await db_session.flush()
    proj = Project(owner_id=u.id, name="识别项目", description="")
    db_session.add(proj)
    await db_session.commit()
    return proj, u


async def _add_dataset(
    db_session: AsyncSession, proj: Project, name: str, content: bytes
) -> Dataset:
    storage = storage_from_settings()
    ds = Dataset(
        project_id=proj.id,
        name=name,
        source_type="csv",
        storage_uri="",
        file_hash="e" * 64,
        file_size=len(content),
        status="VALIDATED",
    )
    db_session.add(ds)
    await db_session.flush()
    ds.storage_uri = storage.put(
        f"datasets/{proj.id}/{ds.id}/{name}", io.BytesIO(content), len(content)
    )
    await db_session.commit()
    return ds


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestDetectTask:
    async def test_survival_200(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, u = user
        ds = await _add_dataset(db_session, proj, "surv.csv", SURVIVAL_CSV)
        resp = await client.post(f"/api/v1/datasets/{ds.id}/detect-task", headers=_auth(u))
        assert resp.status_code == 200
        body = resp.json()
        assert body["recommended_task"] == "survival"
        assert body["confidence"] > 0.8
        assert body["reason"]
        assert body["candidates"]["time_col"][0]["column"] == "os_months"
        assert body["user_override"] is None

    async def test_failure_422(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, u = user
        ds = await _add_dataset(db_session, proj, "none.csv", NO_TARGET_CSV)
        resp = await client.post(f"/api/v1/datasets/{ds.id}/detect-task", headers=_auth(u))
        assert resp.status_code == 422
        assert resp.json()["code"] == "TASK_DETECTION_FAILED"

    async def test_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, _u = user
        ds = await _add_dataset(db_session, proj, "surv2.csv", SURVIVAL_CSV)
        other = User(
            email="td-o@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/detect-task",
            headers={
                "Authorization": f"Bearer {create_token(str(other.id), other.role, 'access')}"
            },
        )
        assert resp.status_code == 404
