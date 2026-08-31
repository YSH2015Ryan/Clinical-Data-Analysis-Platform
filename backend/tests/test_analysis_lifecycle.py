"""T5.9 取消/单模型重跑/janitor 测试（docs/08 §3、docs/12 §3、docs/19 IT-07、docs/20 R1）。

- 取消：终态 400 INVALID_RUN_STATE；进行中 200，RUNNING/PENDING 结果 SKIPPED，
  worker 入口 CANCELED 闸即时生效（取消后再执行 run_model 为空操作）。
- 单模型重跑：仅终态 run；202 后 chain(run_model → compare) 重算 comparison。
- janitor：超时 RUNNING → FAILED（kill -9 恢复）；全模型终态回调未触发 → 手动 compare；
  陈旧 PREPROCESSING → FAILED。
"""

import io
import os
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from app.core.config import get_settings
from app.core.security import create_token, hash_password
from app.engines.model_registry import ModelRegistry
from app.models.entities import (
    AnalysisRun,
    Comparison,
    Dataset,
    DatasetVersion,
    ModelResult,
    Project,
    User,
)
from app.services.plugins import sync_plugins_to_db
from app.services.storage import storage_from_settings
from app.workers import db as worker_db
from app.workers.analysis_tasks import janitor_sweep, run_model
from httpx import AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

CLF_CONFIG = {
    "target": {"label_col": "label"},
    "steps": [{"type": "scale", "params": {}}],
    "validation": {"strategy": "stratified_kfold", "n_splits": 3, "seed": 42},
}


def _clf_csv() -> bytes:
    rng = np.random.default_rng(42)
    n = 60
    age = rng.normal(60, 10, n)
    biomarker = rng.normal(0, 1, n)
    label = (age + 5 * biomarker > 62).astype(int)
    return (
        pd.DataFrame({"age": age, "biomarker": biomarker, "label": label})
        .to_csv(index=False)
        .encode()
    )


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def worker_sync_db(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    monkeypatch.setattr(worker_db, "_factory", sessionmaker(engine, expire_on_commit=False))


@pytest.fixture()
async def researcher(db_session: AsyncSession) -> User:
    user = User(
        email="life@example.com",
        password_hash=hash_password("life-pass"),
        role="researcher",
        display_name="Life",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture()
async def version(db_session: AsyncSession, researcher: User) -> DatasetVersion:
    storage = storage_from_settings()
    uri = storage.put("datasets/test/life_clf.csv", io.BytesIO(_clf_csv()))
    project = Project(owner_id=researcher.id, name="生命周期项目", description="")
    db_session.add(project)
    await db_session.flush()
    dataset = Dataset(
        project_id=project.id,
        name="clf",
        source_type="csv",
        storage_uri=uri,
        file_hash="0" * 64,
        file_size=1,
        status="VALIDATED",
    )
    db_session.add(dataset)
    await db_session.flush()
    v = DatasetVersion(dataset_id=dataset.id, version_no=1, storage_uri=uri, transform_log=[])
    db_session.add(v)
    await db_session.commit()
    return v


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


async def _new_run(
    db_session: AsyncSession,
    researcher: User,
    version: DatasetVersion,
    status: str,
    models: list[str],
    *,
    created_at: datetime | None = None,
) -> AnalysisRun:
    dataset = await db_session.get(Dataset, version.dataset_id)
    registry = ModelRegistry()
    registry.load()
    await sync_plugins_to_db(db_session, registry)  # ModelResult FK 兜底
    run = AnalysisRun(
        project_id=dataset.project_id,
        dataset_version_id=version.id,
        task_type="classification",
        status=status,
        preprocess_config=CLF_CONFIG,
        selected_models=models,
        created_by=researcher.id,
        **({"created_at": created_at} if created_at else {}),
    )
    db_session.add(run)
    await db_session.commit()
    return run


def _result_row(
    run: AnalysisRun, key: str, status: str, *, created_at: datetime | None = None
) -> ModelResult:
    metrics = (
        {"auc": {"mean": 0.9, "std": 0.05, "folds": [0.9, 0.9, 0.9]}}
        if status == "SUCCESS"
        else None
    )
    stale = {"created_at": created_at, "updated_at": created_at} if created_at else {}
    return ModelResult(
        run_id=run.id,
        model_key=key,
        status=status,
        metrics=metrics,
        **stale,
    )


async def _completed_run(
    client: AsyncClient, db_session: AsyncSession, researcher: User, version: DatasetVersion
) -> str:
    resp = await client.post(
        "/api/v1/analysis-runs",
        json={
            "dataset_version_id": str(version.id),
            "task_type": "classification",
            "preprocess_config": CLF_CONFIG,
            "selected_models": ["dummy"],
            "model_params": {},
        },
        headers=_auth(researcher),
    )
    assert resp.status_code == 202
    db_session.expunge_all()
    return str(resp.json()["id"])


class TestCancel:
    async def test_cancel_inflight_200(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run = await _new_run(db_session, researcher, version, "MODELING", ["dummy"])
        db_session.add(_result_row(run, "dummy", "RUNNING"))
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/analysis-runs/{run.id}/cancel", headers=_auth(researcher)
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "CANCELED"

        db_session.expunge_all()
        run2 = await db_session.get(AnalysisRun, run.id)
        assert run2.status == "CANCELED"
        assert run2.finished_at is not None
        result = (
            await db_session.execute(select(ModelResult).where(ModelResult.run_id == run.id))
        ).scalar_one()
        assert result.status == "SKIPPED"
        assert result.error == "运行已取消"

        # 取消即时生效：worker 入口 CANCELED 闸 → run_model 空操作
        run_model(str(run.id), "dummy")
        db_session.expunge_all()
        result2 = (
            await db_session.execute(select(ModelResult).where(ModelResult.run_id == run.id))
        ).scalar_one()
        assert result2.status == "SKIPPED"

    async def test_cancel_terminal_400(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await _completed_run(client, db_session, researcher, version)
        resp = await client.post(
            f"/api/v1/analysis-runs/{run_id}/cancel", headers=_auth(researcher)
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_RUN_STATE"

    async def test_cancel_not_found_404(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.post(
            f"/api/v1/analysis-runs/{uuid.uuid4()}/cancel", headers=_auth(researcher)
        )
        assert resp.status_code == 404


class TestRerun:
    async def test_rerun_202_recomputes(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await _completed_run(client, db_session, researcher, version)
        before = (
            await db_session.execute(
                select(ModelResult).where(ModelResult.run_id == uuid.UUID(run_id))
            )
        ).scalar_one()

        resp = await client.post(
            f"/api/v1/analysis-runs/{run_id}/models/dummy/rerun", headers=_auth(researcher)
        )
        assert resp.status_code == 202

        db_session.expunge_all()
        run = await db_session.get(AnalysisRun, uuid.UUID(run_id))
        assert run.status == "COMPLETED"  # eager：重跑 + compare 同步完成
        after = (
            await db_session.execute(
                select(ModelResult).where(ModelResult.run_id == uuid.UUID(run_id))
            )
        ).scalar_one()
        assert after.status == "SUCCESS"
        assert after.id == before.id  # 同行 upsert 重算（幂等）
        comparison = (
            await db_session.execute(select(Comparison).where(Comparison.run_id == run.id))
        ).scalar_one()
        assert comparison.ranking == ["dummy"]

    async def test_rerun_active_400(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run = await _new_run(db_session, researcher, version, "MODELING", ["dummy"])
        resp = await client.post(
            f"/api/v1/analysis-runs/{run.id}/models/dummy/rerun", headers=_auth(researcher)
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_RUN_STATE"

    async def test_rerun_model_not_selected_400(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await _completed_run(client, db_session, researcher, version)
        resp = await client.post(
            f"/api/v1/analysis-runs/{run_id}/models/logreg/rerun", headers=_auth(researcher)
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"


class TestJanitor:
    async def test_stale_running_failed_and_compare_recovered(
        self, db_session: AsyncSession, researcher: User, version: DatasetVersion
    ) -> None:
        """kill -9 恢复：超时 RUNNING → FAILED；全模型终态 → 手动触发 compare（R1 降级）。"""
        # 陈旧阈值跟随部署配置（hotfix 4b45c3a 后 model_timeout_s=4200），不硬编码秒数
        old = _now() - timedelta(seconds=get_settings().model_timeout_s + 60)
        run = await _new_run(db_session, researcher, version, "MODELING", ["logreg", "dummy"])
        db_session.add(_result_row(run, "logreg", "SUCCESS"))
        db_session.add(_result_row(run, "dummy", "RUNNING", created_at=old))
        await db_session.commit()

        stats = janitor_sweep()

        assert stats["stale_models_failed"] == 1
        assert stats["compare_recovered"] == 1
        db_session.expunge_all()
        run2 = await db_session.get(AnalysisRun, run.id)
        assert run2.status == "COMPLETED"  # eager compare 已补触发
        dummy = (
            await db_session.execute(
                select(ModelResult).where(
                    ModelResult.run_id == run.id, ModelResult.model_key == "dummy"
                )
            )
        ).scalar_one()
        assert dummy.status == "FAILED"
        assert "janitor" in (dummy.error or "")
        comparison = (
            await db_session.execute(select(Comparison).where(Comparison.run_id == run.id))
        ).scalar_one()
        assert comparison.ranking == ["logreg"]

    async def test_stale_preprocessing_failed(
        self, db_session: AsyncSession, researcher: User, version: DatasetVersion
    ) -> None:
        # PREPROCESSING 按单任务超时（model_timeout_s）判定僵死（T5.9 契约）
        old = _now() - timedelta(seconds=get_settings().model_timeout_s + 60)
        run = await _new_run(
            db_session, researcher, version, "PREPROCESSING", ["dummy"], created_at=old
        )
        stats = janitor_sweep()
        assert stats["runs_failed"] == 1
        db_session.expunge_all()
        run2 = await db_session.get(AnalysisRun, run.id)
        assert run2.status == "FAILED"
        assert "janitor" in (run2.error or "")
        assert run2.finished_at is not None

    async def test_fresh_run_untouched(
        self, db_session: AsyncSession, researcher: User, version: DatasetVersion
    ) -> None:
        run = await _new_run(db_session, researcher, version, "MODELING", ["dummy"])
        db_session.add(_result_row(run, "dummy", "RUNNING"))
        await db_session.commit()

        stats = janitor_sweep()

        assert stats == {"stale_models_failed": 0, "compare_recovered": 0, "runs_failed": 0}
        db_session.expunge_all()
        run2 = await db_session.get(AnalysisRun, run.id)
        assert run2.status == "MODELING"

    async def test_all_terminal_failed_triggers_compare(
        self, db_session: AsyncSession, researcher: User, version: DatasetVersion
    ) -> None:
        run = await _new_run(db_session, researcher, version, "MODELING", ["dummy"])
        db_session.add(_result_row(run, "dummy", "FAILED"))
        await db_session.commit()

        stats = janitor_sweep()

        assert stats["compare_recovered"] == 1
        db_session.expunge_all()
        run2 = await db_session.get(AnalysisRun, run.id)
        assert run2.status == "FAILED"
        assert run2.error == "全部模型失败"
