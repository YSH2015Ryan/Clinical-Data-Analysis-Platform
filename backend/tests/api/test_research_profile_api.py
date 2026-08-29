"""API coverage for the research-profile endpoint."""

import io

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, Project, User
from app.services.storage import storage_from_settings
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

CSV_BYTES = (
    "age,os_months,death\n" + "\n".join(f"{40 + i},{6 + i},{i % 2}" for i in range(12))
).encode()


@pytest.fixture()
async def dataset(db_session: AsyncSession) -> tuple[Dataset, User]:
    user = User(
        email="profile@example.com",
        password_hash=hash_password("profile-pass"),
        role="researcher",
        display_name="Profile",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(owner_id=user.id, name="Profile project", description="")
    db_session.add(project)
    await db_session.flush()
    dataset = Dataset(
        project_id=project.id,
        name="profile.csv",
        source_type="csv",
        storage_uri="",
        file_hash="p" * 64,
        file_size=len(CSV_BYTES),
        status="VALIDATED",
    )
    db_session.add(dataset)
    await db_session.flush()
    dataset.storage_uri = storage_from_settings().put(
        f"datasets/{project.id}/{dataset.id}/profile.csv", io.BytesIO(CSV_BYTES), len(CSV_BYTES)
    )
    await db_session.commit()
    return dataset, user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestResearchProfileAPI:
    async def test_research_profile_endpoint(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/research-profile",
            headers=_auth(user),
            json={"outcome": "death"},
        )
        assert response.status_code == 200
        assert response.json()["research_type"] == "cohort"

    async def test_research_profile_invalid_dataset(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        _ds, user = dataset
        response = await client.post(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000000/research-profile",
            headers=_auth(user),
        )
        assert response.status_code == 404

    async def test_research_profile_response_structure(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/research-profile", headers=_auth(user)
        )
        assert response.status_code == 200
        assert set(response.json()) == {
            "research_type",
            "recommended_models",
            "recommended_journals",
            "confidence",
            "reasoning",
            "research_questions",
        }

    async def test_research_questions_none_when_switch_off(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        """T6.7：分功能开关默认 off → research_questions 为 None（纯规则结果）。"""
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/research-profile", headers=_auth(user)
        )
        assert response.status_code == 200
        assert response.json()["research_questions"] is None

    async def test_research_questions_from_llm_when_enabled(
        self,
        client: AsyncClient,
        dataset: tuple[Dataset, User],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T6.7：开关打开 → LLM 增强研究问题进入响应（LLM 层 mock，不依赖真实模型）。"""
        from app.services import llm_tasks
        from app.services import settings as settings_service

        await settings_service.update_llm_config(
            db_session, feature_switches={"research_profile": "local"}
        )
        await db_session.commit()
        monkeypatch.setattr(
            "app.api.v1.datasets.init_llm_service_from_runtime", lambda cfg: object()
        )
        questions = [
            {
                "question": "年龄是否与死亡风险相关？",
                "design": "单因素 Cox 回归",
                "models": ["coxph"],
                "charts": ["KM 生存曲线"],
            }
        ]
        monkeypatch.setattr(llm_tasks, "generate_research_questions", lambda *args: questions)
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/research-profile", headers=_auth(user)
        )
        assert response.status_code == 200
        assert response.json()["research_questions"] == questions

    async def test_llm_failure_falls_back_to_rule_result(
        self,
        client: AsyncClient,
        dataset: tuple[Dataset, User],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T6.7 DoD：LLM 不可用时回退规则输出（research_questions=None），主流程不阻塞。"""
        from app.services import llm_tasks
        from app.services import settings as settings_service

        await settings_service.update_llm_config(
            db_session, feature_switches={"research_profile": "local"}
        )
        await db_session.commit()
        monkeypatch.setattr(
            "app.api.v1.datasets.init_llm_service_from_runtime", lambda cfg: object()
        )
        monkeypatch.setattr(llm_tasks, "generate_research_questions", lambda *args: None)
        ds, user = dataset
        response = await client.post(
            f"/api/v1/datasets/{ds.id}/research-profile", headers=_auth(user)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["research_type"] == "cohort"  # 规则结果仍在
        assert body["research_questions"] is None
