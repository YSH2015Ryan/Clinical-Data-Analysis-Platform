"""T2.1 上传 API 测试：白名单/magic 嗅探/大小上限/202 入库入队（docs/12 §2.5）。"""

import pytest
from app.core.config import get_settings
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, DatasetVersion, Project, User
from app.workers.dataset_tasks import validate_dataset
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CSV_BYTES = b"id,age\n1,55\n2,61\n"


@pytest.fixture()
async def researcher(db_session: AsyncSession) -> User:
    user = User(
        email="up@example.com",
        password_hash=hash_password("up-pass"),
        role="researcher",
        display_name="Up",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture()
async def project(db_session: AsyncSession, researcher: User) -> Project:
    proj = Project(owner_id=researcher.id, name="上传测试项目", description="")
    db_session.add(proj)
    await db_session.commit()
    return proj


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


def _upload(client: AsyncClient, project_id: object, filename: str, content: bytes, user: User):
    return client.post(
        f"/api/v1/projects/{project_id}/datasets",
        files={"file": (filename, content)},
        headers=_auth(user),
    )


class TestUploadHappyPath:
    async def test_csv_accepted_202(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Celery is eager globally for task tests; this endpoint contract only
        # verifies the enqueue transaction and should remain VALIDATING until a worker runs.
        monkeypatch.setattr(validate_dataset, "delay", lambda *_args, **_kwargs: None)
        resp = await _upload(client, project.id, "cohort.csv", CSV_BYTES, researcher)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "VALIDATING"

        dataset = (
            await db_session.execute(select(Dataset).where(Dataset.id == body["dataset_id"]))
        ).scalar_one()
        assert dataset.status == "VALIDATING"
        assert dataset.source_type == "csv"
        assert dataset.file_size == len(CSV_BYTES)
        assert len(dataset.file_hash) == 64

        version = (
            await db_session.execute(
                select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
            )
        ).scalar_one()
        assert version.version_no == 1
        assert version.storage_uri == dataset.storage_uri

    async def test_xlsx_magic_ok(
        self, client: AsyncClient, researcher: User, project: Project
    ) -> None:
        xlsx_head = b"PK\x03\x04" + b"\x00" * 100
        resp = await _upload(client, project.id, "cohort.xlsx", xlsx_head, researcher)
        assert resp.status_code == 202


class TestUploadGuards:
    async def test_bad_extension_400(
        self, client: AsyncClient, researcher: User, project: Project
    ) -> None:
        resp = await _upload(client, project.id, "evil.exe", b"MZ\x90\x00", researcher)
        assert resp.status_code == 400
        assert resp.json()["code"] == "UNSUPPORTED_FILE_TYPE"

    async def test_disguised_xlsx_400(
        self, client: AsyncClient, researcher: User, project: Project
    ) -> None:
        resp = await _upload(client, project.id, "fake.xlsx", CSV_BYTES, researcher)
        assert resp.status_code == 400
        assert resp.json()["code"] == "UNSUPPORTED_FILE_TYPE"

    async def test_binary_as_csv_400(
        self, client: AsyncClient, researcher: User, project: Project
    ) -> None:
        resp = await _upload(client, project.id, "fake.csv", b"a,b\x00\x00\x00", researcher)
        assert resp.status_code == 400
        assert resp.json()["code"] == "UNSUPPORTED_FILE_TYPE"

    async def test_oversize_413(
        self,
        client: AsyncClient,
        researcher: User,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
        resp = await _upload(client, project.id, "big.csv", CSV_BYTES, researcher)
        assert resp.status_code == 413
        assert resp.json()["code"] == "FILE_TOO_LARGE"

    async def test_viewer_403(
        self, client: AsyncClient, db_session: AsyncSession, project: Project
    ) -> None:
        viewer = User(
            email="v@example.com",
            password_hash=hash_password("v-pass"),
            role="viewer",
            display_name="V",
        )
        db_session.add(viewer)
        await db_session.commit()
        resp = await _upload(client, project.id, "a.csv", CSV_BYTES, viewer)
        assert resp.status_code == 403

    async def test_cross_owner_project_404(
        self, client: AsyncClient, db_session: AsyncSession, project: Project
    ) -> None:
        other = User(
            email="o@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await _upload(client, project.id, "a.csv", CSV_BYTES, other)
        assert resp.status_code == 404
        assert resp.json()["code"] == "PROJECT_NOT_FOUND"
