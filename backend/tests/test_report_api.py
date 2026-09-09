"""T7.5 报告 API 测试（docs/14 /reports 冻结契约；docs/10 §4）。

POST /reports → 202 落库 + eager 生成 READY；历史列表按时间倒序；
download：READY → 200 直接返回文件内容；PENDING → 400
REPORT_NOT_READY；未知 → 404；跨属主 → 403；非 COMPLETED 运行 → 400。
"""

import uuid

import pytest
from app.core.security import hash_password
from app.models.entities import AnalysisRun, Dataset, DatasetVersion, Report, User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_analysis_api import _auth, _body
from tests.test_analysis_api import researcher as _researcher_impl
from tests.test_analysis_api import version as _version_impl
from tests.test_analysis_api import worker_sync_db as _ws_impl

# 共享 fixture 再导出（pytest 按模块属性名发现）
researcher = _researcher_impl
version = _version_impl
worker_sync_db = _ws_impl

API = "/api/v1"


async def _completed_run_id(client: AsyncClient, user: User, version: DatasetVersion) -> uuid.UUID:
    resp = await client.post(
        f"{API}/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(user)
    )
    assert resp.status_code == 202
    return uuid.UUID(resp.json()["id"])


@pytest.mark.usefixtures("worker_sync_db")
class TestCreateReport:
    async def test_create_202_and_ready(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await _completed_run_id(client, researcher, version)
        resp = await client.post(
            f"{API}/reports",
            json={"run_id": str(run_id), "format": "html"},
            headers=_auth(researcher),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["run_id"] == str(run_id)
        assert body["template_key"] == "clinical_report_zh"

        # eager：生成已同步完成
        db_session.expunge_all()
        report = await db_session.get(Report, uuid.UUID(body["id"]))
        assert report is not None and report.status == "READY"
        assert report.storage_uri and report.storage_uri.endswith("report.html")

    async def test_run_not_completed_400(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        dataset = await db_session.get(Dataset, version.dataset_id)
        run = AnalysisRun(
            project_id=dataset.project_id,
            dataset_version_id=version.id,
            task_type="classification",
            status="MODELING",
            preprocess_config={},
            selected_models=["dummy"],
            created_by=researcher.id,
        )
        db_session.add(run)
        await db_session.commit()

        resp = await client.post(
            f"{API}/reports",
            json={"run_id": str(run.id), "format": "pdf"},
            headers=_auth(researcher),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_RUN_STATE"

    async def test_run_not_found_404(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        resp = await client.post(
            f"{API}/reports",
            json={"run_id": str(uuid.uuid4()), "format": "html"},
            headers=_auth(researcher),
        )
        assert resp.status_code == 404

    async def test_cross_owner_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await _completed_run_id(client, researcher, version)
        other = User(
            email="other@example.com",
            password_hash=hash_password("other-pass"),
            role="researcher",
            display_name="Other",
        )
        db_session.add(other)
        await db_session.commit()

        resp = await client.post(
            f"{API}/reports",
            json={"run_id": str(run_id), "format": "html"},
            headers=_auth(other),
        )
        assert resp.status_code == 403


@pytest.mark.usefixtures("worker_sync_db")
class TestListAndDownload:
    async def test_history_list_desc(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        run_id = await _completed_run_id(client, researcher, version)
        for fmt in ("html", "pdf"):
            resp = await client.post(
                f"{API}/reports",
                json={"run_id": str(run_id), "format": fmt},
                headers=_auth(researcher),
            )
            assert resp.status_code == 202

        resp = await client.get(f"{API}/analysis-runs/{run_id}/reports", headers=_auth(researcher))
        assert resp.status_code == 200
        items = resp.json()
        # P1-4：run 完成时自动生成 1 份 HTML 报告 + 本测试手动创建 2 份
        assert len(items) == 3
        assert {i["format"] for i in items} == {"html", "pdf"}
        assert sum(1 for i in items if i["format"] == "html") == 2
        assert items[0]["created_at"] >= items[1]["created_at"]  # 倒序

    async def test_download_200_content_and_headers(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await _completed_run_id(client, researcher, version)
        created = await client.post(
            f"{API}/reports",
            json={"run_id": str(run_id), "format": "html"},
            headers=_auth(researcher),
        )
        report_id = created.json()["id"]
        # 测试会话跨请求共享（conftest client fixture），须清身份映射以读取
        # worker 独立会话提交的 READY 状态（与 test_create_202_and_ready 同模式）
        db_session.expunge_all()
        resp = await client.get(
            f"{API}/reports/{report_id}/download",
            headers=_auth(researcher),
        )
        assert resp.status_code == 200
        assert resp.content
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.headers["content-disposition"] == 'inline; filename="report.html"'

    async def test_download_not_ready_400(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await _completed_run_id(client, researcher, version)
        pending = Report(run_id=run_id, format="pdf", created_by=researcher.id)
        db_session.add(pending)
        await db_session.commit()

        resp = await client.get(f"{API}/reports/{pending.id}/download", headers=_auth(researcher))
        assert resp.status_code == 400
        assert resp.json()["code"] == "REPORT_NOT_READY"

    async def test_download_not_found_404(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        resp = await client.get(f"{API}/reports/{uuid.uuid4()}/download", headers=_auth(researcher))
        assert resp.status_code == 404

    async def test_download_cross_owner_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await _completed_run_id(client, researcher, version)
        created = await client.post(
            f"{API}/reports",
            json={"run_id": str(run_id), "format": "html"},
            headers=_auth(researcher),
        )
        other = User(
            email="other2@example.com",
            password_hash=hash_password("other-pass"),
            role="researcher",
            display_name="Other2",
        )
        db_session.add(other)
        await db_session.commit()

        resp = await client.get(
            f"{API}/reports/{created.json()['id']}/download", headers=_auth(other)
        )
        assert resp.status_code == 403
