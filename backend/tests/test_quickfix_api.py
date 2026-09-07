"""T2.6 Quick Fix API 测试：新版本生成/原文件不变/预览刷新/隔离（docs/14 §3、docs/05 §5）。"""

import io

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import (
    Dataset,
    DatasetVersion,
    Project,
    QualityReport,
    User,
)
from app.services.storage import storage_from_settings
from app.workers.insight_tasks import auto_dataset_insight
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def _no_insight_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """阶段 A 体检任务单独在 test_dataset_insight 覆盖；此处避免 eager 执行触库。"""
    monkeypatch.setattr(auto_dataset_insight, "delay", lambda *_a, **_k: None)

# 含 RV301（alt=未知）+ RV401（1 行完全重复）
CSV = (
    b"patient_id,age,alt,os_months,death\n"
    b"P1,55,10,12,1\n"
    b"P2,61,\xe6\x9c\xaa\xe7\x9f\xa5,24,0\n"  # alt=未知
    b"P3,47,30,8,1\n"
    b"P3,47,30,8,1\n"
)


@pytest.fixture()
async def researcher(db_session: AsyncSession) -> User:
    user = User(
        email="qf@example.com",
        password_hash=hash_password("qf-pass"),
        role="researcher",
        display_name="QF",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture()
async def dataset(db_session: AsyncSession, researcher: User) -> Dataset:
    proj = Project(owner_id=researcher.id, name="修复项目", description="")
    db_session.add(proj)
    await db_session.flush()
    storage = storage_from_settings()
    ds = Dataset(
        project_id=proj.id,
        name="cohort.csv",
        source_type="csv",
        storage_uri="",
        file_hash="b" * 64,
        file_size=len(CSV),
        status="VALIDATED",
    )
    db_session.add(ds)
    await db_session.flush()
    key = f"datasets/{proj.id}/{ds.id}/cohort.csv"
    uri = storage.put(key, io.BytesIO(CSV), len(CSV))
    ds.storage_uri = uri
    db_session.add(DatasetVersion(dataset_id=ds.id, version_no=1, storage_uri=uri))
    await db_session.commit()
    return ds


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestQuickFix:
    async def test_new_version_and_preview_updated(
        self, client: AsyncClient, db_session: AsyncSession, researcher: User, dataset: Dataset
    ) -> None:
        original_uri = dataset.storage_uri
        resp = await client.post(
            f"/api/v1/datasets/{dataset.id}/quick-fix",
            json={
                "actions": [{"type": "drop_duplicates"}, {"type": "to_missing", "column": "alt"}]
            },
            headers=_auth(researcher),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["version_no"] == 2
        assert len(body["transform_log"]) == 2

        # 原文件不变
        storage = storage_from_settings()
        from app.services.storage import key_from_uri

        assert storage.get(key_from_uri(original_uri)) == CSV

        # 预览刷新：4 行 → 3 行，alt 的「未知」→ None
        await db_session.refresh(dataset)
        assert dataset.preview["total_rows"] == 3
        versions = (
            (
                await db_session.execute(
                    select(DatasetVersion)
                    .where(DatasetVersion.dataset_id == dataset.id)
                    .order_by(DatasetVersion.version_no)
                )
            )
            .scalars()
            .all()
        )
        assert len(versions) == 2
        # 新版本产生新质量报告
        reports = (
            (
                await db_session.execute(
                    select(QualityReport).where(QualityReport.dataset_id == dataset.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(reports) == 1
        assert reports[0].dataset_version_id == versions[1].id

    async def test_versions_list(
        self, client: AsyncClient, researcher: User, dataset: Dataset
    ) -> None:
        resp = await client.get(
            f"/api/v1/datasets/{dataset.id}/versions", headers=_auth(researcher)
        )
        assert resp.status_code == 200
        assert [v["version_no"] for v in resp.json()] == [1]

    async def test_invalid_action_400(
        self, client: AsyncClient, researcher: User, dataset: Dataset
    ) -> None:
        resp = await client.post(
            f"/api/v1/datasets/{dataset.id}/quick-fix",
            json={"actions": [{"type": "drop_column", "column": "nope"}]},
            headers=_auth(researcher),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    async def test_viewer_403(
        self, client: AsyncClient, db_session: AsyncSession, dataset: Dataset
    ) -> None:
        viewer = User(
            email="qf-v@example.com",
            password_hash=hash_password("v-pass"),
            role="viewer",
            display_name="V",
        )
        db_session.add(viewer)
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/datasets/{dataset.id}/quick-fix",
            json={"actions": [{"type": "drop_duplicates"}]},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    async def test_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, dataset: Dataset
    ) -> None:
        other = User(
            email="qf-o@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/datasets/{dataset.id}/quick-fix",
            json={"actions": [{"type": "drop_duplicates"}]},
            headers=_auth(other),
        )
        assert resp.status_code == 404
