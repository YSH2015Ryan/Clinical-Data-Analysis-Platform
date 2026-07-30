"""T3.1 DSL 校验端点测试：非法 DSL 400 / 合法 200 / 隔离（docs/14 §3）。"""

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, Project, User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

VALID_DSL = {
    "target": {"label_col": "death"},
    "steps": [{"type": "scale", "params": {"method": "standard"}}],
    "validation": {"strategy": "kfold", "n_splits": 3, "seed": 42},
}

INVALID_DSL = {
    "target": {"label_col": "death"},
    "steps": [{"type": "scale", "params": {"method": "magic"}}],
    "validation": {"strategy": "kfold", "n_splits": 3, "seed": 42},
}


@pytest.fixture()
async def dataset(db_session: AsyncSession) -> tuple[Dataset, User]:
    user = User(
        email="dsl@example.com",
        password_hash=hash_password("dsl-pass"),
        role="researcher",
        display_name="DSL",
    )
    db_session.add(user)
    await db_session.flush()
    proj = Project(owner_id=user.id, name="DSL 项目", description="")
    db_session.add(proj)
    await db_session.flush()
    ds = Dataset(
        project_id=proj.id,
        name="a.csv",
        source_type="csv",
        storage_uri=".test_storage/datasets/x/a.csv",
        file_hash="c" * 64,
        file_size=10,
        status="VALIDATED",
    )
    db_session.add(ds)
    await db_session.commit()
    return ds, user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestPreprocessValidate:
    async def test_valid_200(self, client: AsyncClient, dataset: tuple[Dataset, User]) -> None:
        ds, user = dataset
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/validate",
            json=VALID_DSL,
            headers=_auth(user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["normalized"]["steps"][0]["params"]["method"] == "standard"

    async def test_invalid_400(self, client: AsyncClient, dataset: tuple[Dataset, User]) -> None:
        ds, user = dataset
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/validate",
            json=INVALID_DSL,
            headers=_auth(user),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    async def test_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, dataset: tuple[Dataset, User]
    ) -> None:
        ds, _ = dataset
        other = User(
            email="dsl-o@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/validate",
            json=VALID_DSL,
            headers=_auth(other),
        )
        assert resp.status_code == 404
