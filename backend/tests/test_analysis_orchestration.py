"""T5.8 编排集成测试（docs/08 §2-3；docs/19 M2）：

- chain(preprocess → chord(models, comparison)) 端到端：eager 模式同步执行，
  worker 同步会话指向 TEST_DATABASE_URL（monkeypatch app.workers.db 工厂）。
- 状态机：PENDING → … → COMPLETED；单模型失败隔离；全部失败 → run FAILED。
- compute_progress 进度公式（08 §3）：纯函数用例不需 DB。
"""

import io
import os
import uuid

import numpy as np
import pandas as pd
import pytest
from app.core.security import hash_password
from app.engines.model_registry import ModelRegistry
from app.models.entities import (
    AnalysisRun,
    Comparison,
    Dataset,
    DatasetVersion,
    ModelResult,
    PreprocessSnapshot,
    Project,
    User,
)
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.auth import CurrentUser
from app.services import analysis as analysis_service
from app.services.storage import storage_from_settings
from app.workers import db as worker_db
from app.workers.analysis_tasks import dispatch_analysis_run
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

CSV_KEY = "datasets/test/clf.csv"
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


@pytest.fixture()
def worker_sync_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """worker 任务（eager 同步执行）的 sync session 指向测试库。"""
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    monkeypatch.setattr(worker_db, "_factory", sessionmaker(engine, expire_on_commit=False))


@pytest.fixture()
async def seeded(db_session: AsyncSession) -> tuple[User, DatasetVersion]:
    storage = storage_from_settings()
    uri = storage.put(CSV_KEY, io.BytesIO(_clf_csv()))
    user = User(
        email="orch@example.com",
        password_hash=hash_password("orch-pass"),
        role="researcher",
        display_name="Orch",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(owner_id=user.id, name="编排项目", description="")
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
    version = DatasetVersion(dataset_id=dataset.id, version_no=1, storage_uri=uri, transform_log=[])
    db_session.add(version)
    await db_session.commit()
    return user, version


def _registry() -> ModelRegistry:
    registry = ModelRegistry()
    registry.load()
    return registry


async def _create_run(
    db_session: AsyncSession,
    user: User,
    version: DatasetVersion,
    models: list[str],
    model_params: dict[str, dict[str, object]] | None = None,
) -> AnalysisRun:
    body = AnalysisRunCreate(
        dataset_version_id=version.id,
        task_type="classification",
        preprocess_config=CLF_CONFIG,
        selected_models=models,
        model_params=model_params or {},
    )
    caller = CurrentUser(id=user.id, email=str(user.email), role=user.role)
    run = await analysis_service.create_run(db_session, caller, body, registry=_registry())
    await db_session.commit()
    return run


def _fetch_run(run_id: uuid.UUID) -> tuple[AnalysisRun, list[ModelResult]]:
    factory = worker_db.get_sync_session_factory()
    with factory() as db:
        run = db.get(AnalysisRun, run_id)
        assert run is not None
        results = (
            db.execute(select(ModelResult).where(ModelResult.run_id == run.id)).scalars().all()
        )
        db.expunge_all()
        return run, list(results)


@pytest.mark.usefixtures("worker_sync_db")
class TestOrchestration:
    async def test_chain_to_completed(
        self, db_session: AsyncSession, seeded: tuple[User, DatasetVersion]
    ) -> None:
        user, version = seeded
        run = await _create_run(db_session, user, version, ["logreg", "rf"])
        assert run.status == "PENDING"

        dispatch_analysis_run(str(run.id), ["logreg", "rf"])

        done, results = _fetch_run(run.id)
        assert done.status == "COMPLETED"
        assert done.finished_at is not None
        assert {r.model_key for r in results} == {"logreg", "rf"}
        for r in results:
            assert r.status == "SUCCESS"
            assert r.error is None
            assert r.duration_ms is not None and r.duration_ms >= 0
            auc = r.metrics["auc"]
            assert 0.0 <= auc["mean"] <= 1.0
            assert len(auc["folds"]) == 3  # n_splits=3
            assert set(auc) == {"mean", "std", "folds"}

        # 预处理快照 + 特征矩阵落存储
        factory = worker_db.get_sync_session_factory()
        with factory() as db:
            snap = db.execute(
                select(PreprocessSnapshot).where(PreprocessSnapshot.run_id == run.id)
            ).scalar_one()
            assert snap.steps
            comparison = db.execute(
                select(Comparison).where(Comparison.run_id == run.id)
            ).scalar_one()
        assert sorted(comparison.ranking) == ["logreg", "rf"]
        rec = comparison.recommendation
        assert rec["primary_metric"] == "auc"
        assert rec["top"][0]["model_key"] == comparison.ranking[0]
        assert "auc=" in rec["top"][0]["reason"]

        # 进度终态 100
        progress = analysis_service.compute_progress(done, results)
        assert progress["percent"] == 100
        assert progress["models"] == {"logreg": "SUCCESS", "rf": "SUCCESS"}

    async def test_single_model_failure_isolated(
        self, db_session: AsyncSession, seeded: tuple[User, DatasetVersion]
    ) -> None:
        """logreg 非法参数失败不影响 dummy；run 仍 COMPLETED（docs/07 §4）。"""
        user, version = seeded
        run = await _create_run(
            db_session, user, version, ["logreg", "dummy"], {"logreg": {"C": -1.0}}
        )
        dispatch_analysis_run(str(run.id), ["logreg", "dummy"])

        done, results = _fetch_run(run.id)
        by_key = {r.model_key: r for r in results}
        assert by_key["logreg"].status == "FAILED"
        assert by_key["logreg"].error
        assert by_key["dummy"].status == "SUCCESS"
        assert done.status == "COMPLETED"

        factory = worker_db.get_sync_session_factory()
        with factory() as db:
            comparison = db.execute(
                select(Comparison).where(Comparison.run_id == run.id)
            ).scalar_one()
        assert comparison.ranking == ["dummy"]  # 失败模型不参与排名

    async def test_all_models_failed_run_failed(
        self, db_session: AsyncSession, seeded: tuple[User, DatasetVersion]
    ) -> None:
        user, version = seeded
        run = await _create_run(db_session, user, version, ["logreg"], {"logreg": {"C": -1.0}})
        dispatch_analysis_run(str(run.id), ["logreg"])

        done, _ = _fetch_run(run.id)
        assert done.status == "FAILED"
        assert done.error == "全部模型失败"

    async def test_preprocess_failure_marks_run_failed(
        self, db_session: AsyncSession, seeded: tuple[User, DatasetVersion]
    ) -> None:
        """预处理异常（target 列不存在）→ run FAILED，chord 不执行。"""
        user, version = seeded
        bad_config = {**CLF_CONFIG, "target": {"label_col": "missing_col"}}
        body = AnalysisRunCreate(
            dataset_version_id=version.id,
            task_type="classification",
            preprocess_config=bad_config,
            selected_models=["dummy"],
        )
        caller = CurrentUser(id=user.id, email=str(user.email), role=user.role)
        run = await analysis_service.create_run(db_session, caller, body, registry=_registry())
        await db_session.commit()

        # eager 模式下任务异常会传播给调用方（生产 apply_async 仅入队，不抛出）
        with pytest.raises(KeyError):
            dispatch_analysis_run(str(run.id), ["dummy"])

        done, results = _fetch_run(run.id)
        assert done.status == "FAILED"
        assert "preprocess" in (done.error or "")
        assert results == []  # chain 中止，chord 未执行

    async def test_rerun_idempotent(
        self, db_session: AsyncSession, seeded: tuple[User, DatasetVersion]
    ) -> None:
        """重复 dispatch 幂等：snapshot/comparison 唯一约束兜底（docs/18 T5.8 DoD）。"""
        user, version = seeded
        run = await _create_run(db_session, user, version, ["dummy"])
        dispatch_analysis_run(str(run.id), ["dummy"])
        dispatch_analysis_run(str(run.id), ["dummy"])

        done, results = _fetch_run(run.id)
        assert done.status == "COMPLETED"
        assert len(results) == 1
        factory = worker_db.get_sync_session_factory()
        with factory() as db:
            snaps = (
                db.execute(select(PreprocessSnapshot).where(PreprocessSnapshot.run_id == run.id))
                .scalars()
                .all()
            )
            comparisons = (
                db.execute(select(Comparison).where(Comparison.run_id == run.id)).scalars().all()
            )
        assert len(snaps) == 1
        assert len(comparisons) == 1


class TestProgressFormula:
    """compute_progress 纯函数用例（docs/08 §3 公式），不触 DB。"""

    @staticmethod
    def _run(status: str, models: list[str]) -> AnalysisRun:
        run = AnalysisRun(
            project_id=uuid.uuid4(),
            dataset_version_id=uuid.uuid4(),
            task_type="classification",
            status=status,
            preprocess_config={},
            selected_models=models,
            created_by=uuid.uuid4(),
        )
        return run

    @staticmethod
    def _result(key: str, status: str) -> ModelResult:
        return ModelResult(run_id=uuid.uuid4(), model_key=key, status=status)

    def test_pending_zero(self) -> None:
        progress = analysis_service.compute_progress(self._run("PENDING", ["a"]), [])
        assert progress["percent"] == 0
        assert progress["models"] == {"a": "PENDING"}

    def test_preprocessing(self) -> None:
        progress = analysis_service.compute_progress(self._run("PREPROCESSING", ["a"]), [])
        assert progress["percent"] == 10
        assert progress["current_step"] == "preprocess"

    def test_modeling_partial(self) -> None:
        run = self._run("MODELING", ["a", "b"])
        results = [self._result("a", "SUCCESS"), self._result("b", "RUNNING")]
        progress = analysis_service.compute_progress(run, results)
        assert progress["percent"] == 20 + 35  # 70% 的一半
        assert progress["current_step"] == "model:b"

    def test_modeling_failed_counts_as_done(self) -> None:
        run = self._run("MODELING", ["a", "b"])
        results = [self._result("a", "FAILED"), self._result("b", "SUCCESS")]
        progress = analysis_service.compute_progress(run, results)
        assert progress["percent"] == 90

    def test_comparing(self) -> None:
        progress = analysis_service.compute_progress(self._run("COMPARING", ["a"]), [])
        assert progress["percent"] == 90
        assert progress["current_step"] == "comparison"

    def test_completed(self) -> None:
        progress = analysis_service.compute_progress(self._run("COMPLETED", ["a"]), [])
        assert progress["percent"] == 100
