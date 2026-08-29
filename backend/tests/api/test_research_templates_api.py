"""API coverage for the research-templates endpoint (T6.9)."""

import io

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, Project, User
from app.services.storage import storage_from_settings
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# 队列数据：随访 + 事件 + 特征（预后模型/危险因素模板应适用）
CSV_BYTES = (
    "age,bmi,os_months,death\n"
    + "\n".join(f"{40 + i % 20},{20 + i % 8},{6 + i % 30},{i % 2}" for i in range(40))
).encode()


@pytest.fixture()
async def dataset(db_session: AsyncSession) -> tuple[Dataset, User]:
    user = User(
        email="templates@example.com",
        password_hash=hash_password("templates-pass"),
        role="researcher",
        display_name="Templates",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(owner_id=user.id, name="Templates project", description="")
    db_session.add(project)
    await db_session.flush()
    dataset = Dataset(
        project_id=project.id,
        name="templates.csv",
        source_type="csv",
        storage_uri="",
        file_hash="t" * 64,
        file_size=len(CSV_BYTES),
        status="VALIDATED",
    )
    db_session.add(dataset)
    await db_session.flush()
    dataset.storage_uri = storage_from_settings().put(
        f"datasets/{project.id}/{dataset.id}/templates.csv", io.BytesIO(CSV_BYTES), len(CSV_BYTES)
    )
    await db_session.commit()
    return dataset, user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestResearchTemplatesAPI:
    async def test_templates_endpoint_structure(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        response = await client.get(
            f"/api/v1/datasets/{ds.id}/research-templates", headers=_auth(user)
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"templates"}
        assert len(body["templates"]) == 4
        for t in body["templates"]:
            assert set(t) == {
                "key",
                "name",
                "description",
                "applicable",
                "reasons",
                "task_type",
                "models",
                "charts",
                "sample_size",
            }
            for advice in t["sample_size"]:
                assert set(advice) == {"rule", "value", "threshold", "meets", "text"}

    async def test_cohort_dataset_prognostic_applicable(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        response = await client.get(
            f"/api/v1/datasets/{ds.id}/research-templates", headers=_auth(user)
        )
        templates = {t["key"]: t for t in response.json()["templates"]}
        prognostic = templates["prognostic_model"]
        assert prognostic["applicable"] is True
        assert prognostic["task_type"] == "survival"
        assert "coxph" in prognostic["models"]
        epv = prognostic["sample_size"][0]
        assert epv["value"] is not None  # 真实 EPV 已计算

    async def test_templates_invalid_dataset(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        _ds, user = dataset
        response = await client.get(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000000/research-templates",
            headers=_auth(user),
        )
        assert response.status_code == 404

    async def test_templates_requires_auth(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000000/research-templates"
        )
        assert response.status_code == 401
