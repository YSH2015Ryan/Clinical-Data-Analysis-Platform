"""API coverage for univariate-screen / subgroup-analysis endpoints (T6.10)."""

import io

import numpy as np
import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, Project, User
from app.services.storage import storage_from_settings
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _csv_bytes() -> bytes:
    rng = np.random.default_rng(42)
    n = 120
    age = rng.normal(60, 10, n)
    logit = -6 + 0.1 * age
    y = (rng.uniform(0, 1, n) < 1 / (1 + np.exp(-logit))).astype(int)
    treated = rng.integers(0, 2, n)
    sex = rng.integers(0, 2, n)
    lines = ["outcome,age,treated,sex"]
    lines += [f"{y[i]},{age[i]:.2f},{treated[i]},{sex[i]}" for i in range(n)]
    return "\n".join(lines).encode()


@pytest.fixture()
async def dataset(db_session: AsyncSession) -> tuple[Dataset, User]:
    user = User(
        email="screen@example.com",
        password_hash=hash_password("screen-pass"),
        role="researcher",
        display_name="Screen",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(owner_id=user.id, name="Screen project", description="")
    db_session.add(project)
    await db_session.flush()
    data = _csv_bytes()
    dataset = Dataset(
        project_id=project.id,
        name="screen.csv",
        source_type="csv",
        storage_uri="",
        file_hash="s" * 64,
        file_size=len(data),
        status="VALIDATED",
    )
    db_session.add(dataset)
    await db_session.flush()
    dataset.storage_uri = storage_from_settings().put(
        f"datasets/{project.id}/{dataset.id}/screen.csv", io.BytesIO(data), len(data)
    )
    await db_session.commit()
    return dataset, user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestUnivariateScreenAPI:
    async def test_screen_classification(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/univariate-screen",
            headers=_auth(user),
            json={"task_type": "classification", "label_col": "outcome"},
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"task_type", "alpha", "rows", "selected_features"}
        assert "age" in body["selected_features"]
        features = [r["feature"] for r in body["rows"]]
        assert "outcome" not in features

    async def test_screen_missing_label_400(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/univariate-screen",
            headers=_auth(user),
            json={"task_type": "classification"},
        )
        assert response.status_code == 400

    async def test_screen_404(self, client: AsyncClient, dataset: tuple[Dataset, User]) -> None:
        _ds, user = dataset
        response = await client.post(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000000/univariate-screen",
            headers=_auth(user),
            json={"task_type": "classification", "label_col": "outcome"},
        )
        assert response.status_code == 404


class TestSubgroupAnalysisAPI:
    async def test_subgroup_classification(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/subgroup-analysis",
            headers=_auth(user),
            json={
                "task_type": "classification",
                "exposure": "treated",
                "label_col": "outcome",
                "subgroup_vars": ["sex"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"task_type", "exposure", "subgroups"}
        sub = body["subgroups"][0]
        assert sub["variable"] == "sex"
        assert len(sub["levels"]) == 2
        for lv in sub["levels"]:
            assert lv["n"] > 0
            if lv["effect"] is not None:
                assert lv["ci_lower"] <= lv["effect"] <= lv["ci_upper"]

    async def test_subgroup_invalid_var_400(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/subgroup-analysis",
            headers=_auth(user),
            json={
                "task_type": "classification",
                "exposure": "treated",
                "label_col": "outcome",
                "subgroup_vars": ["nope"],
            },
        )
        assert response.status_code == 400

    async def test_subgroup_requires_auth(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000000/subgroup-analysis",
            json={
                "task_type": "classification",
                "exposure": "treated",
                "subgroup_vars": ["sex"],
            },
        )
        assert response.status_code == 401
