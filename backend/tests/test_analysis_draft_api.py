"""P1-3 分析草稿端点测试（GET /datasets/{id}/analysis-draft，docs/14 §5 变更记录 2026-09-07）。

契约：单页确认所需全部默认值一次返回 —— 推荐任务类型（含 task_detection）、
推荐预处理配置、该任务的标准套餐模型 key 列表；无列画像 → 400。
"""

import io
import uuid

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, DatasetVersion, Project, User
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
        email=f"draft-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("draft-pass"),
        role="researcher",
        display_name="DRAFT",
    )
    db_session.add(user)
    await db_session.flush()
    proj = Project(owner_id=user.id, name="草稿项目", description="")
    db_session.add(proj)
    await db_session.flush()
    storage = storage_from_settings()
    ds = Dataset(
        project_id=proj.id,
        name="a.csv",
        source_type="csv",
        storage_uri="",
        file_hash="e" * 64,
        file_size=len(CSV_BYTES),
        status="VALIDATED",
    )
    db_session.add(ds)
    await db_session.flush()
    key = f"datasets/{proj.id}/{ds.id}/a.csv"
    ds.storage_uri = storage.put(key, io.BytesIO(CSV_BYTES), len(CSV_BYTES))
    from app.engines import parser, validation

    parsed = parser.parse(CSV_BYTES, "csv")
    ds.column_profile = validation.validate(
        parsed.df, raw_columns=parsed.raw_columns
    ).column_profiles
    db_session.add(
        DatasetVersion(dataset_id=ds.id, version_no=1, storage_uri=ds.storage_uri, transform_log=[])
    )
    await db_session.commit()
    return ds, user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestAnalysisDraft:
    async def test_200_full_defaults(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        resp = await client.get(f"/api/v1/datasets/{ds.id}/analysis-draft", headers=_auth(user))
        assert resp.status_code == 200
        body = resp.json()
        # 有 0/1 death 列 → 推荐分类
        assert body["task_type"] == "classification"
        assert body["task_detection"]["recommended_task"] == "classification"
        cfg = body["preprocess_config"]
        assert cfg["validation"]["seed"] == 42
        assert cfg["target"].get("label_col") == "death"
        assert isinstance(cfg["steps"], list) and cfg["steps"]
        # 标准套餐非空且全部是该任务可用模型
        assert len(body["standard_models"]) >= 2

    async def test_400_without_profile(
        self, client: AsyncClient, db_session: AsyncSession, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        ds.column_profile = None
        await db_session.commit()
        resp = await client.get(f"/api/v1/datasets/{ds.id}/analysis-draft", headers=_auth(user))
        assert resp.status_code == 400

    async def test_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, dataset: tuple[Dataset, User]
    ) -> None:
        ds, _ = dataset
        other = User(
            email=f"draft-o-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="DO",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.get(f"/api/v1/datasets/{ds.id}/analysis-draft", headers=_auth(other))
        assert resp.status_code == 404
