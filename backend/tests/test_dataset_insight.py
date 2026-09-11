"""P1-1/P2-2 阶段 A 流水线测试（workers/insight_tasks.py，docs/08 §3.2）。

契约：校验成功后自动续跑 —— 安全项自动修复（impute/to_missing/winsorize，
全部生成新 DatasetVersion）→ EDA → 任务推荐 → 研究画像 → 落库 DatasetInsight；
任务幂等（重跑替换旧 insight，不重复修复）；仍有 blocker 即停止修复。
"""

import io
import os
import uuid
from typing import Any, ClassVar

import pytest
from app.models.base import Base
from app.models.entities import Dataset, DatasetInsight, DatasetVersion, Project, User
from app.services.storage import storage_from_settings
from app.workers import db as worker_db
from app.workers import insight_tasks
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

# 故意制造：bmi 缺失（RV201 warning）、wbc 一个极端异常值（RV501/RV804 warning）
_CLEAN_CSV = (
    "patient_id,age,gender,death\n"
    + "\n".join(f"P{i:03d},{20 + i % 40},{'男' if i % 2 else '女'},{i % 2}" for i in range(60))
).encode("utf-8")

_FIXABLE_CSV = (
    "patient_id,age,bmi,death\n"
    + "\n".join(
        # 30% 缺失（> missing_warn 0.2，< missing_block 0.5）→ RV201 warning
        f"P{i:03d},{20 + i % 40},{'' if i % 10 < 3 else 22.0 + i % 8},{i % 2}"
        for i in range(60)
    )
).encode("utf-8")


@pytest.fixture()
def sync_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.create_all(engine)  # 独立运行本文件时保证 dataset_insights 等表存在
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "_factory", factory)
    with factory() as db:
        yield db


def _make_dataset(db: Any, csv: bytes, *, name: str = "cohort.csv") -> Dataset:
    user = User(
        email=f"insight-{uuid.uuid4().hex[:12]}@example.com",
        password_hash="x",
        role="researcher",
        display_name="INS",
    )
    db.add(user)
    db.flush()
    proj = Project(owner_id=user.id, name="体检项目", description="")
    db.add(proj)
    db.flush()
    ds = Dataset(
        project_id=proj.id,
        name=name,
        source_type="csv",
        storage_uri="",
        file_hash="i" * 64,
        file_size=len(csv),
        status="VALIDATED",
    )
    db.add(ds)
    db.flush()
    key = f"datasets/{proj.id}/{ds.id}/{name}"
    ds.storage_uri = storage_from_settings().put(key, io.BytesIO(csv), len(csv))
    db.add(
        DatasetVersion(dataset_id=ds.id, version_no=1, storage_uri=ds.storage_uri, transform_log=[])
    )
    db.commit()
    return ds


def _insight(db: Any, dataset_id: Any) -> DatasetInsight | None:
    return db.execute(
        select(DatasetInsight).where(DatasetInsight.dataset_id == dataset_id)
    ).scalar_one_or_none()


class TestInsightHappyPath:
    def test_clean_dataset_persists_insight(self, sync_db: Any) -> None:
        ds = _make_dataset(sync_db, _CLEAN_CSV)
        insight_tasks.auto_dataset_insight(str(ds.id))
        ins = _insight(sync_db, ds.id)
        assert ins is not None
        payload = ins.payload
        assert set(payload) >= {
            "eda",
            "task_recommendation",
            "research_profile",
            "auto_fix_log",
            "summary",
        }
        # EDA 真实数值
        assert payload["eda"]["row_count"] == 60
        assert payload["eda"]["sample_size"]["n_rows"] == 60
        # 干净数据不产生修复
        assert payload["auto_fix_log"] == []
        # 有 0/1 death 列 → 规则推荐非空
        assert payload["task_recommendation"]["recommended_tasks"]
        # 研究画像规则产出
        assert payload["research_profile"]["research_type"]
        assert isinstance(payload["summary"], list) and payload["summary"]
        # T6.14：干净数据(60 例/3 特征/30 事件,EPV=10,年龄性别列齐备)无缺口
        assert payload["supplement_plan"]["items"] == []
        assert payload["supplement_plan"]["overall"]

    def test_insight_points_at_latest_version(self, sync_db: Any) -> None:
        ds = _make_dataset(sync_db, _CLEAN_CSV)
        insight_tasks.auto_dataset_insight(str(ds.id))
        ins = _insight(sync_db, ds.id)
        v = sync_db.get(DatasetVersion, ins.dataset_version_id)
        assert v is not None and v.dataset_id == ds.id


class TestSupplementPlanWiring:
    """T6.14 接入:体检流水线产出 supplement_plan(引擎真实数值,docs/14 §5 已登记)。"""

    # 92 例、40 特征、28 阳性 → EPV=0.7(实据场景复刻)
    _EPV_DEFICIT_CSV = (
        "death,"
        + ",".join(f"f{j:02d}" for j in range(40))
        + "\n"
        + "\n".join(
            f"{1 if i < 28 else 0}," + ",".join(str((i * 7 + j) % 10) for j in range(40))
            for i in range(92)
        )
    ).encode("utf-8")

    def test_epv_deficit_plan_real_numbers(self, sync_db: Any) -> None:
        ds = _make_dataset(sync_db, self._EPV_DEFICIT_CSV, name="epv.csv")
        insight_tasks.auto_dataset_insight(str(ds.id))
        ins = _insight(sync_db, ds.id)
        assert ins is not None
        plan = ins.payload["supplement_plan"]
        item = next(i for i in plan["items"] if i["deficit_type"] == "epv")
        # 契约形状(docs/14 §5 变更记录 2026-09-09)
        assert set(item) == {
            "deficit_type",
            "current",
            "target",
            "gap",
            "suggestion",
            "basis",
        }
        assert item["current"]["epv"] == 0.7
        assert item["gap"]["missing_events"] == 372  # ⌈10×40 − 28⌉
        assert item["gap"]["additional_rows"] == 1223  # ⌈372/(28/92)⌉
        # 体检结论摘要含缺口总览行
        assert any("数据缺口" in line for line in ins.payload["summary"])


class TestAutoFix:
    def test_missing_warning_auto_imputed(self, sync_db: Any) -> None:
        ds = _make_dataset(sync_db, _FIXABLE_CSV)
        insight_tasks.auto_dataset_insight(str(ds.id))
        ins = _insight(sync_db, ds.id)
        assert ins is not None
        log = ins.payload["auto_fix_log"]
        kinds = {(e["action"], e["column"]) for e in log}
        assert ("impute_missing", "bmi") in kinds
        # 修复生成新 DatasetVersion（版本号递增，源版本不变）
        versions = (
            sync_db.execute(
                select(DatasetVersion)
                .where(DatasetVersion.dataset_id == ds.id)
                .order_by(DatasetVersion.version_no)
            )
            .scalars()
            .all()
        )
        assert len(versions) >= 2
        assert versions[0].version_no == 1
        # EDA 基于修复后数据：bmi 缺失应为 0
        bmi = next(d for d in ins.payload["eda"]["distributions"] if d["name"] == "bmi")
        assert bmi["missing"] == 0

    def test_blocker_stops_fixing(self, sync_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """仍有 blocker 即停止（不自动修复根本性问题，留给用户决策）。"""
        from app.engines import validation

        real_validate = validation.validate

        class _FakeReport:
            status = "FAILED"
            blockers = 1
            warnings = 0
            issues: ClassVar[list[Any]] = []
            column_profiles: ClassVar[list[dict[str, Any]]] = []

        monkeypatch.setattr(insight_tasks.validation, "validate", lambda *a, **k: _FakeReport())
        ds = _make_dataset(sync_db, _CLEAN_CSV)
        insight_tasks.auto_dataset_insight(str(ds.id))
        versions = sync_db.execute(
            select(func.count())
            .select_from(DatasetVersion)
            .where(DatasetVersion.dataset_id == ds.id)
        ).scalar_one()
        assert versions == 1  # 未产生修复版本
        monkeypatch.setattr(insight_tasks.validation, "validate", real_validate)


class TestIdempotency:
    def test_rerun_replaces_insight_no_duplicate_fix(self, sync_db: Any) -> None:
        ds = _make_dataset(sync_db, _FIXABLE_CSV)
        insight_tasks.auto_dataset_insight(str(ds.id))
        first_versions = sync_db.execute(
            select(func.count())
            .select_from(DatasetVersion)
            .where(DatasetVersion.dataset_id == ds.id)
        ).scalar_one()
        insight_tasks.auto_dataset_insight(str(ds.id))
        # 第二次跑：缺失已补齐 → 不再产生新修复版本
        second_versions = sync_db.execute(
            select(func.count())
            .select_from(DatasetVersion)
            .where(DatasetVersion.dataset_id == ds.id)
        ).scalar_one()
        assert second_versions == first_versions
        # insight 仍只有一条（替换而非累积）
        rows = sync_db.execute(
            select(func.count())
            .select_from(DatasetInsight)
            .where(DatasetInsight.dataset_id == ds.id)
        ).scalar_one()
        assert rows == 1


class TestRobustness:
    def test_missing_dataset_returns_silently(self, sync_db: Any) -> None:
        insight_tasks.auto_dataset_insight("00000000-0000-0000-0000-000000000000")


class TestInsightApi:
    """GET /datasets/{id}/insight（docs/14 §5 变更记录 2026-09-07）。"""

    async def test_404_before_insight_generated(self, client: Any, db_session: Any) -> None:
        from app.core.security import create_token, hash_password

        user = User(
            email=f"insight-api-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("p"),
            role="researcher",
            display_name="IA",
        )
        db_session.add(user)
        await db_session.flush()
        proj = Project(owner_id=user.id, name="P", description="")
        db_session.add(proj)
        await db_session.flush()
        ds = Dataset(
            project_id=proj.id,
            name="x.csv",
            source_type="csv",
            storage_uri="unused",
            file_hash="z" * 64,
            file_size=1,
            status="VALIDATED",
        )
        db_session.add(ds)
        await db_session.commit()
        resp = await client.get(
            f"/api/v1/datasets/{ds.id}/insight",
            headers={"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"},
        )
        assert resp.status_code == 404

    async def test_200_after_worker_run(self, client: Any, db_session: Any, sync_db: Any) -> None:
        from app.core.security import create_token, hash_password

        user = User(
            email=f"insight-api2-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("p"),
            role="researcher",
            display_name="IA2",
        )
        db_session.add(user)
        await db_session.flush()
        proj = Project(owner_id=user.id, name="P2", description="")
        db_session.add(proj)
        await db_session.flush()
        ds = Dataset(
            project_id=proj.id,
            name="cohort.csv",
            source_type="csv",
            storage_uri="",
            file_hash="y" * 64,
            file_size=len(_CLEAN_CSV),
            status="VALIDATED",
        )
        db_session.add(ds)
        await db_session.flush()
        key = f"datasets/{proj.id}/{ds.id}/cohort.csv"
        ds.storage_uri = storage_from_settings().put(key, io.BytesIO(_CLEAN_CSV), len(_CLEAN_CSV))
        db_session.add(
            DatasetVersion(
                dataset_id=ds.id, version_no=1, storage_uri=ds.storage_uri, transform_log=[]
            )
        )
        await db_session.commit()

        insight_tasks.auto_dataset_insight(str(ds.id))  # worker 同步会话写同一测试库

        resp = await client.get(
            f"/api/v1/datasets/{ds.id}/insight",
            headers={"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dataset_id"] == str(ds.id)
        assert body["payload"]["eda"]["row_count"] == 60
        assert body["payload"]["summary"]
        # T6.14:API 透出 supplement_plan 结构(docs/14 §5 变更记录 2026-09-09)
        assert body["payload"]["supplement_plan"]["items"] == []
        assert body["payload"]["supplement_plan"]["overall"]
