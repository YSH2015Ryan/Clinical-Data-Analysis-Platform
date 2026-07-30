"""T3.5/T3.6 推荐配置端点测试：合法 200 + 隔离 404（docs/14 §3，契约变更 2026-07-30）。"""

import io

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, Project, User
from app.services.storage import storage_from_settings
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

CSV_BYTES = (
    "patient_id,age,gender,wbc,death\n"
    + "\n".join(
        f"P{i:03d},{20 + i},{'男' if i % 2 else '女'},{5.0 + i * 0.1},{i % 2}" for i in range(20)
    )
).encode("utf-8")


@pytest.fixture()
async def dataset(db_session: AsyncSession) -> tuple[Dataset, User]:
    user = User(
        email="rec@example.com",
        password_hash=hash_password("rec-pass"),
        role="researcher",
        display_name="REC",
    )
    db_session.add(user)
    await db_session.flush()
    proj = Project(owner_id=user.id, name="推荐项目", description="")
    db_session.add(proj)
    await db_session.flush()
    storage = storage_from_settings()
    ds = Dataset(
        project_id=proj.id,
        name="a.csv",
        source_type="csv",
        storage_uri="",
        file_hash="d" * 64,
        file_size=len(CSV_BYTES),
        status="VALIDATED",
    )
    db_session.add(ds)
    await db_session.flush()
    key = f"datasets/{proj.id}/{ds.id}/a.csv"
    ds.storage_uri = storage.put(key, io.BytesIO(CSV_BYTES), len(CSV_BYTES))
    await db_session.commit()
    return ds, user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestPreprocessRecommend:
    async def test_recommend_200(self, client: AsyncClient, dataset: tuple[Dataset, User]) -> None:
        ds, user = dataset
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/recommend", headers=_auth(user)
        )
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        assert cfg["validation"]["seed"] == 42
        assert cfg["target"].get("label_col") == "death"
        types = [s["type"] for s in cfg["steps"]]
        assert "drop_columns" in types and "missing" in types

    async def test_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, dataset: tuple[Dataset, User]
    ) -> None:
        ds, _ = dataset
        other = User(
            email="rec-o@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/recommend", headers=_auth(other)
        )
        assert resp.status_code == 404
