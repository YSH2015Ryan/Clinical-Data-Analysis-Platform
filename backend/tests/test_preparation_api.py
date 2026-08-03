"""P0-1d 数据准备 API + worker 测试（docs/05 §8、docs/14 §3 preparation 端点）。

- preview：列识别/词条/建议默认值；跨项目诊断表 400；越权 404。
- apply：202 → eager 同步执行 worker → 任务 COMPLETED + 宽表数据集落库可直接分析。
- get：任务状态查询；越权 404。
"""

import io
import os
import uuid

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, Project, User
from app.services.storage import storage_from_settings
from app.workers import db as worker_db
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

LAB_CSV = (
    "患者ID,诊断日期,化验日期,检验名称,检验标本,化验单位,异常,归一化值\n"
    "P001,2020-02-01,2020-01-25,葡萄糖,血,mmol/L,,0.5\n"
    "P001,2020-02-01,2020-01-28,葡萄糖,血,mmol/L,,0.7\n"
    "P001,2020-02-01,2020-01-10,白细胞计数,血,10^9/L,,0.4\n"
    "P001,2020-02-01,2020-01-15,万古霉素,血,,敏感（S）,\n"
    "P002,2020-01-05,2020-01-03,葡萄糖,血,mmol/L,,0.6\n"
    "P002,2020-01-05,2020-01-04,白细胞计数,血,10^9/L,,0.5\n"
).encode()

DIAG_CSV = (
    "患者ID,诊断日期,诊断,年龄,性别\n"
    "P001,2020-01-01,~炎症,60,男\n"
    "P001,2020-02-01,~恶性肿瘤;~癌,60,男\n"
    "P002,2020-01-05,~炎症;~上呼吸道感染,45,女\n"
).encode()

DECISIONS = {
    "outcome_terms": ["恶性肿瘤"],
    "index_diagnosis": "last",
    "window_days": 60,
}


@pytest.fixture()
def worker_sync_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """worker 任务（eager 同步执行）的 sync session 指向测试库。"""
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    monkeypatch.setattr(worker_db, "_factory", sessionmaker(engine, expire_on_commit=False))


@pytest.fixture()
async def user(db_session: AsyncSession) -> tuple[Project, User]:
    u = User(
        email="prep@example.com",
        password_hash=hash_password("prep-pass"),
        role="researcher",
        display_name="Prep",
    )
    db_session.add(u)
    await db_session.flush()
    proj = Project(owner_id=u.id, name="准备项目", description="")
    db_session.add(proj)
    await db_session.commit()
    return proj, u


async def _add_dataset(
    db_session: AsyncSession, proj: Project, name: str, content: bytes
) -> Dataset:
    storage = storage_from_settings()
    ds = Dataset(
        project_id=proj.id,
        name=name,
        source_type="csv",
        storage_uri="",
        file_hash="e" * 64,
        file_size=len(content),
        status="VALIDATED",
    )
    db_session.add(ds)
    await db_session.flush()
    ds.storage_uri = storage.put(
        f"datasets/{proj.id}/{ds.id}/{name}", io.BytesIO(content), len(content)
    )
    await db_session.commit()
    return ds


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestPreview:
    async def test_preview_200(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, u = user
        lab = await _add_dataset(db_session, proj, "化验.csv", LAB_CSV)
        diag = await _add_dataset(db_session, proj, "诊断.csv", DIAG_CSV)
        resp = await client.post(
            f"/api/v1/datasets/{lab.id}/preparation/preview",
            json={"diagnosis_dataset_id": str(diag.id)},
            headers=_auth(u),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["lab_columns"]["item"] == "检验名称"
        assert body["diag_columns"]["text"] == "诊断"
        assert body["patients_intersection"] == 2
        assert body["susceptibility_rows"] == 1
        terms = {t["term"]: t["count"] for t in body["diagnosis_terms"]}
        assert terms["炎症"] == 2 and terms["恶性肿瘤"] == 1
        assert body["suggested"]["window_days"] == 30

    async def test_cross_project_diag_400(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, u = user
        other_proj = Project(owner_id=u.id, name="另一项目", description="")
        db_session.add(other_proj)
        await db_session.commit()
        lab = await _add_dataset(db_session, proj, "化验.csv", LAB_CSV)
        diag = await _add_dataset(db_session, other_proj, "诊断.csv", DIAG_CSV)
        resp = await client.post(
            f"/api/v1/datasets/{lab.id}/preparation/preview",
            json={"diagnosis_dataset_id": str(diag.id)},
            headers=_auth(u),
        )
        assert resp.status_code == 400

    async def test_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, _u = user
        lab = await _add_dataset(db_session, proj, "化验.csv", LAB_CSV)
        diag = await _add_dataset(db_session, proj, "诊断.csv", DIAG_CSV)
        other = User(
            email="prep-o@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/datasets/{lab.id}/preparation/preview",
            json={"diagnosis_dataset_id": str(diag.id)},
            headers=_auth(other),
        )
        assert resp.status_code == 404


@pytest.mark.usefixtures("worker_sync_db")
class TestApply:
    async def test_apply_completes_with_wide_dataset(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, u = user
        lab = await _add_dataset(db_session, proj, "化验.csv", LAB_CSV)
        diag = await _add_dataset(db_session, proj, "诊断.csv", DIAG_CSV)
        resp = await client.post(
            f"/api/v1/datasets/{lab.id}/preparation/apply",
            json={"diagnosis_dataset_id": str(diag.id), "decisions": DECISIONS},
            headers=_auth(u),
        )
        assert resp.status_code == 202
        job = resp.json()
        assert job["status"] == "COMPLETED"  # eager 同步执行
        assert job["result_dataset_id"]
        assert job["summary"]["patients"] == 2
        assert job["summary"]["label_positive"] == 1
        assert job["summary"]["susceptibility_removed"] == 1

        # 产物数据集可查询且通过校验（可直接进入分析）
        ds_resp = await client.get(f"/api/v1/datasets/{job['result_dataset_id']}", headers=_auth(u))
        assert ds_resp.status_code == 200
        assert ds_resp.json()["status"] == "VALIDATED"
        qr = await client.get(
            f"/api/v1/datasets/{job['result_dataset_id']}/quality-report", headers=_auth(u)
        )
        assert qr.status_code == 200
        assert all(i["rule_id"] != "RV101" for i in qr.json()["issues"])

        # 轮询端点返回同一任务
        poll = await client.get(f"/api/v1/preparations/{job['id']}", headers=_auth(u))
        assert poll.status_code == 200
        assert poll.json()["status"] == "COMPLETED"

    async def test_get_job_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, u = user
        lab = await _add_dataset(db_session, proj, "化验.csv", LAB_CSV)
        diag = await _add_dataset(db_session, proj, "诊断.csv", DIAG_CSV)
        resp = await client.post(
            f"/api/v1/datasets/{lab.id}/preparation/apply",
            json={"diagnosis_dataset_id": str(diag.id), "decisions": DECISIONS},
            headers=_auth(u),
        )
        job_id = resp.json()["id"]
        other = User(
            email="prep-o2@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O2",
        )
        db_session.add(other)
        await db_session.commit()
        poll = await client.get(f"/api/v1/preparations/{job_id}", headers=_auth(other))
        assert poll.status_code == 404

    async def test_bad_decisions_400(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        proj, u = user
        lab = await _add_dataset(db_session, proj, "化验.csv", LAB_CSV)
        diag = await _add_dataset(db_session, proj, "诊断.csv", DIAG_CSV)
        resp = await client.post(
            f"/api/v1/datasets/{lab.id}/preparation/apply",
            json={"diagnosis_dataset_id": str(diag.id), "decisions": {"outcome_terms": []}},
            headers=_auth(u),
        )
        assert resp.status_code == 400  # 空结局词条：契约校验拒绝（项目统一 VALIDATION_ERROR）

    async def test_missing_value_column_fails_job(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        """引擎中文报错落入 job.error（结果真实红线：失败可审计）。"""
        proj, u = user
        lab = await _add_dataset(db_session, proj, "化验.csv", LAB_CSV)
        diag = await _add_dataset(db_session, proj, "诊断.csv", DIAG_CSV)
        resp = await client.post(
            f"/api/v1/datasets/{lab.id}/preparation/apply",
            json={
                "diagnosis_dataset_id": str(diag.id),
                "decisions": {**DECISIONS, "value_column": "不存在的列"},
            },
            headers=_auth(u),
        )
        assert resp.status_code == 202
        job = resp.json()
        assert job["status"] == "FAILED"
        assert "不存在的列" in job["error"]


@pytest.mark.usefixtures("worker_sync_db")
class TestWorkerIdempotent:
    async def test_completed_rerun_noop(
        self, client: AsyncClient, db_session: AsyncSession, user: tuple[Project, User]
    ) -> None:
        from app.workers.preparation_tasks import run_preparation

        proj, u = user
        lab = await _add_dataset(db_session, proj, "化验.csv", LAB_CSV)
        diag = await _add_dataset(db_session, proj, "诊断.csv", DIAG_CSV)
        resp = await client.post(
            f"/api/v1/datasets/{lab.id}/preparation/apply",
            json={"diagnosis_dataset_id": str(diag.id), "decisions": DECISIONS},
            headers=_auth(u),
        )
        job = resp.json()
        result_id = job["result_dataset_id"]
        run_preparation(job["id"])  # 重投：不重复产出
        poll = await client.get(f"/api/v1/preparations/{job['id']}", headers=_auth(u))
        assert poll.json()["result_dataset_id"] == result_id
        assert uuid.UUID(result_id)  # 合法 uuid 未变
