"""T2.5 质量报告 API 测试：列表/详情/报告 + 项目级隔离（docs/14 §3、docs/12 §2.2）。"""

import uuid

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import (
    Dataset,
    DatasetVersion,
    Project,
    QualityReport,
    User,
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture()
async def researcher(db_session: AsyncSession) -> User:
    user = User(
        email="qr@example.com",
        password_hash=hash_password("qr-pass"),
        role="researcher",
        display_name="QR",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture()
async def project(db_session: AsyncSession, researcher: User) -> Project:
    proj = Project(owner_id=researcher.id, name="质量报告项目", description="")
    db_session.add(proj)
    await db_session.commit()
    return proj


@pytest.fixture()
async def dataset(db_session: AsyncSession, project: Project) -> Dataset:
    ds = Dataset(
        project_id=project.id,
        name="cohort.csv",
        source_type="csv",
        storage_uri=".test_storage/datasets/x/cohort.csv",
        file_hash="a" * 64,
        file_size=123,
        encoding="utf-8",
        status="VALIDATED",
        preview={"columns": ["age"], "rows": [[55]], "total_rows": 1},
        column_profile=[{"name": "age", "inferred_type": "continuous", "semantic": "Age"}],
    )
    db_session.add(ds)
    await db_session.commit()
    return ds


@pytest.fixture()
async def version(db_session: AsyncSession, dataset: Dataset) -> DatasetVersion:
    v = DatasetVersion(
        dataset_id=dataset.id, version_no=1, storage_uri=dataset.storage_uri, transform_log=[]
    )
    db_session.add(v)
    await db_session.commit()
    return v


@pytest.fixture()
async def report(db_session: AsyncSession, dataset: Dataset, version: DatasetVersion):
    r = QualityReport(
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        status="PASSED_WITH_WARNINGS",
        blockers=0,
        warnings=1,
        issues=[
            {
                "rule_id": "RV201",
                "severity": "warning",
                "column": "ALP",
                "message": "缺失率 34.2%",
                "affected_rows": 521,
                "suggestion": "可在预处理中选择中位数插补或删除该列",
            }
        ],
        column_profiles=[{"name": "ALP", "inferred_type": "continuous"}],
    )
    db_session.add(r)
    await db_session.commit()
    return r


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestListDatasets:
    async def test_list_200(
        self, client: AsyncClient, researcher: User, project: Project, dataset: Dataset
    ) -> None:
        resp = await client.get(
            f"/api/v1/projects/{project.id}/datasets", headers=_auth(researcher)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "cohort.csv"
        assert body["items"][0]["status"] == "VALIDATED"
        assert body["next_cursor"] is None

    async def test_list_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, project: Project
    ) -> None:
        other = User(
            email="qr-o@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.get(f"/api/v1/projects/{project.id}/datasets", headers=_auth(other))
        assert resp.status_code == 404


class TestDatasetDetail:
    async def test_detail_200(
        self, client: AsyncClient, researcher: User, dataset: Dataset
    ) -> None:
        resp = await client.get(f"/api/v1/datasets/{dataset.id}", headers=_auth(researcher))
        assert resp.status_code == 200
        body = resp.json()
        assert body["encoding"] == "utf-8"
        assert body["preview"]["total_rows"] == 1
        assert body["column_profile"][0]["semantic"] == "Age"

    async def test_detail_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, dataset: Dataset
    ) -> None:
        other = User(
            email="qr-x@example.com",
            password_hash=hash_password("x-pass"),
            role="researcher",
            display_name="X",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.get(f"/api/v1/datasets/{dataset.id}", headers=_auth(other))
        assert resp.status_code == 404
        assert resp.json()["code"] == "DATASET_NOT_FOUND"

    async def test_detail_unauthenticated_401(self, client: AsyncClient, dataset: Dataset) -> None:
        resp = await client.get(f"/api/v1/datasets/{dataset.id}")
        assert resp.status_code == 401

    async def test_detail_missing_404(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.get(f"/api/v1/datasets/{uuid.uuid4()}", headers=_auth(researcher))
        assert resp.status_code == 404


class TestQualityReportEndpoint:
    async def test_report_200(
        self, client: AsyncClient, researcher: User, dataset: Dataset, report
    ) -> None:
        resp = await client.get(
            f"/api/v1/datasets/{dataset.id}/quality-report", headers=_auth(researcher)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "PASSED_WITH_WARNINGS"
        assert body["blockers"] == 0
        assert body["warnings"] == 1
        assert body["issues"][0]["rule_id"] == "RV201"
        assert body["issues"][0]["suggestion"]
        assert body["column_profiles"][0]["name"] == "ALP"

    async def test_report_not_ready_404(
        self, client: AsyncClient, researcher: User, dataset: Dataset
    ) -> None:
        resp = await client.get(
            f"/api/v1/datasets/{dataset.id}/quality-report", headers=_auth(researcher)
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "REPORT_NOT_FOUND"

    async def test_report_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, dataset: Dataset, report
    ) -> None:
        other = User(
            email="qr-y@example.com",
            password_hash=hash_password("y-pass"),
            role="researcher",
            display_name="Y",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.get(
            f"/api/v1/datasets/{dataset.id}/quality-report", headers=_auth(other)
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "DATASET_NOT_FOUND"
