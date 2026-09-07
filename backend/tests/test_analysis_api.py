"""T5.8 分析运行 API 测试（docs/14 /analysis-runs 冻结契约）。

202 创建并 dispatch（eager 同步执行完整 chain）；409 同数据集进行中；
400 数据集未 VALIDATED / 模型不可用；403 跨属主；进度端点聚合。
"""

import hashlib
import io
import os
import uuid

import numpy as np
import pandas as pd
import pytest
from app.core.security import create_token, hash_password
from app.models.entities import (
    AnalysisRun,
    Dataset,
    DatasetVersion,
    Project,
    User,
)
from app.services.storage import storage_from_settings
from app.workers import db as worker_db
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


def _text_label_csv() -> bytes:
    rng = np.random.default_rng(7)
    n = 60
    return (
        pd.DataFrame(
            {
                "age": rng.normal(60, 10, n),
                "outcome": ["恶性" if i % 2 else "良性" for i in range(n)],
            }
        )
        .to_csv(index=False)
        .encode()
    )


def _imbalanced_csv() -> bytes:
    """类别「1」仅 2 例，少于 n_splits=3 → stratified_kfold 必然失败。"""
    rng = np.random.default_rng(11)
    n = 60
    label = np.zeros(n, dtype=int)
    label[:2] = 1
    return pd.DataFrame({"age": rng.normal(60, 10, n), "label": label}).to_csv(index=False).encode()


def _cfg(target: dict[str, str], strategy: str = "stratified_kfold") -> dict[str, object]:
    return {
        "target": target,
        "steps": [{"type": "scale", "params": {}}],
        "validation": {"strategy": strategy, "n_splits": 3, "seed": 42},
    }


async def _make_version(
    db_session: AsyncSession, researcher: User, csv_bytes: bytes, name: str
) -> DatasetVersion:
    storage = storage_from_settings()
    uri = storage.put(f"datasets/test/{name}.csv", io.BytesIO(csv_bytes))
    project = Project(owner_id=researcher.id, name=f"项目-{name}", description="")
    db_session.add(project)
    await db_session.flush()
    dataset = Dataset(
        project_id=project.id,
        name=name,
        source_type="csv",
        storage_uri=uri,
        file_hash=hashlib.sha256(csv_bytes).hexdigest(),
        file_size=len(csv_bytes),
        status="VALIDATED",
    )
    db_session.add(dataset)
    await db_session.flush()
    v = DatasetVersion(dataset_id=dataset.id, version_no=1, storage_uri=uri, transform_log=[])
    db_session.add(v)
    await db_session.commit()
    return v


@pytest.fixture(autouse=True)
def worker_sync_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST 创建后 eager dispatch 的 worker 会话指向测试库。"""
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    monkeypatch.setattr(worker_db, "_factory", sessionmaker(engine, expire_on_commit=False))


@pytest.fixture()
async def researcher(db_session: AsyncSession) -> User:
    user = User(
        email="ana@example.com",
        password_hash=hash_password("ana-pass"),
        role="researcher",
        display_name="Ana",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture()
async def version(db_session: AsyncSession, researcher: User) -> DatasetVersion:
    return await _make_version(db_session, researcher, _clf_csv(), "api_clf")


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


def _body(
    version_id: uuid.UUID,
    models: list[str],
    model_params: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "dataset_version_id": str(version_id),
        "task_type": "classification",
        "preprocess_config": CLF_CONFIG,
        "selected_models": models,
        "model_params": model_params or {},
    }


class TestTaskDetectionRecorded:
    """P0-2：创建 run 时必须把任务识别依据写入 AnalysisRun.task_detection，
    否则报告「任务识别依据」章节恒为空（此前字段只有读取方没有写入方）。"""

    async def _set_profile(self, db_session: AsyncSession, version: DatasetVersion) -> None:
        dataset = (
            await db_session.execute(select(Dataset).where(Dataset.id == version.dataset_id))
        ).scalar_one()
        dataset.column_profile = [
            {"name": "age", "inferred_type": "continuous", "semantic": "Age",
             "semantic_confidence": 0.9, "missing_rate": 0.0, "unique": 55,
             "min": 30.0, "max": 90.0},
            {"name": "biomarker", "inferred_type": "continuous", "semantic": None,
             "semantic_confidence": 0.0, "missing_rate": 0.0, "unique": 60,
             "min": -2.0, "max": 2.0},
            {"name": "label", "inferred_type": "continuous", "semantic": "Label",
             "semantic_confidence": 0.9, "missing_rate": 0.0, "unique": 2,
             "min": 0.0, "max": 1.0},
        ]
        await db_session.commit()

    async def test_task_detection_written_on_create(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        await self._set_profile(db_session, version)
        resp = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
        )
        assert resp.status_code == 202, resp.text
        run = await db_session.get(AnalysisRun, uuid.UUID(resp.json()["id"]))
        assert run.task_detection is not None
        assert run.task_detection["recommended_task"] == "classification"
        assert run.task_detection["reason"]
        assert run.task_detection["user_override"] is None

    async def test_user_override_recorded_when_diverging(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        await self._set_profile(db_session, version)
        body = {
            "dataset_version_id": str(version.id),
            "task_type": "regression",
            "preprocess_config": {
                "target": {"label_col": "biomarker"},
                "steps": [{"type": "scale", "params": {}}],
                "validation": {"strategy": "kfold", "n_splits": 3, "seed": 42},
            },
            "selected_models": ["lasso"],
            "model_params": {},
        }
        resp = await client.post(
            "/api/v1/analysis-runs", json=body, headers=_auth(researcher)
        )
        assert resp.status_code == 202, resp.text
        run = await db_session.get(AnalysisRun, uuid.UUID(resp.json()["id"]))
        assert run.task_detection is not None
        assert run.task_detection["recommended_task"] == "classification"
        assert run.task_detection["user_override"] == "regression"


class TestCreateRun:
    async def test_create_202_and_completes(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        resp = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["task_type"] == "classification"

        # eager：dispatch 同步执行完整 chain；expunge 强制读 worker 落库的最新状态
        db_session.expunge_all()
        run = (
            await db_session.execute(select(AnalysisRun).where(AnalysisRun.id == body["id"]))
        ).scalar_one()
        assert run.status == "COMPLETED"
        assert run.celery_chain_id

    async def test_auto_html_report_generated_on_complete(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        """P1-4：run COMPLETED 后自动生成 HTML 报告，无需用户手动 POST /reports。"""
        from app.models.entities import Report

        resp = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
        )
        assert resp.status_code == 202
        db_session.expunge_all()
        reports = (
            await db_session.execute(
                select(Report).where(Report.run_id == uuid.UUID(resp.json()["id"]))
            )
        ).scalars().all()
        html_reports = [r for r in reports if r.format == "html"]
        assert len(html_reports) == 1
        assert html_reports[0].status == "READY"  # eager 模式同步渲染完成

    async def test_run_already_active_409(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run = AnalysisRun(
            project_id=(await db_session.get(Dataset, version.dataset_id)).project_id,
            dataset_version_id=version.id,
            task_type="classification",
            status="MODELING",
            preprocess_config=CLF_CONFIG,
            selected_models=["dummy"],
            created_by=researcher.id,
        )
        db_session.add(run)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "RUN_ALREADY_ACTIVE"

    async def test_dataset_not_validated_400(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        dataset = await db_session.get(Dataset, version.dataset_id)
        dataset.status = "UPLOADED"
        await db_session.commit()

        resp = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "DATASET_NOT_READY"

    async def test_plugin_unavailable_400(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        resp = await client.post(
            "/api/v1/analysis-runs",
            json=_body(version.id, ["no_such_model"]),
            headers=_auth(researcher),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "PLUGIN_UNAVAILABLE"

    async def test_task_type_mismatch_400(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        """dummy 仅支持 classification；survival 任务 → PLUGIN_UNAVAILABLE。

        time/event 指向真实存在的列，确保 400 来自插件校验而非 target 存在性校验。
        """
        body = _body(version.id, ["dummy"])
        body["task_type"] = "survival"
        body["preprocess_config"] = {
            "target": {"time_col": "age", "event_col": "label"},
            "steps": [{"type": "scale", "params": {}}],
            "validation": {"strategy": "kfold", "n_splits": 3, "seed": 42},
        }
        resp = await client.post("/api/v1/analysis-runs", json=body, headers=_auth(researcher))
        assert resp.status_code == 400
        assert resp.json()["code"] == "PLUGIN_UNAVAILABLE"

    async def test_viewer_403(
        self, client: AsyncClient, db_session: AsyncSession, version: DatasetVersion
    ) -> None:
        viewer = User(
            email="viewer@example.com",
            password_hash=hash_password("v-pass"),
            role="viewer",
            display_name="V",
        )
        db_session.add(viewer)
        await db_session.commit()
        resp = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(viewer)
        )
        assert resp.status_code == 403

    async def test_bad_dsl_400(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        body = _body(version.id, ["dummy"])
        body["preprocess_config"] = {"steps": []}
        resp = await client.post("/api/v1/analysis-runs", json=body, headers=_auth(researcher))
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    async def test_survival_missing_target_human_message(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        """survival 缺 time_col/event_col → 400 且文案面向非技术用户（含改选分类指引）。"""
        body = _body(version.id, ["dummy"])
        body["task_type"] = "survival"
        resp = await client.post("/api/v1/analysis-runs", json=body, headers=_auth(researcher))
        assert resp.status_code == 400
        msg = resp.json()["message"]
        assert "随访时间" in msg and "分类" in msg

    async def test_regression_stratified_kfold_coerced(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        """docs/06 §2：回归任务配 stratified_kfold 必败，落库前强制降级 kfold。"""
        body = _body(version.id, ["lasso"])
        body["task_type"] = "regression"
        body["preprocess_config"] = dict(CLF_CONFIG)  # 合法 DSL + stratified_kfold
        resp = await client.post("/api/v1/analysis-runs", json=body, headers=_auth(researcher))
        assert resp.status_code == 202
        db_session.expunge_all()
        run = (
            await db_session.execute(select(AnalysisRun).where(AnalysisRun.id == resp.json()["id"]))
        ).scalar_one()
        assert run.preprocess_config["validation"]["strategy"] == "kfold"


class TestTargetDataChecks:
    """数据级硬校验（docs/06 §2，2026-08-10）：只拦数学上必然失败的情形。"""

    async def test_regression_text_label_400(
        self, client: AsyncClient, db_session: AsyncSession, researcher: User
    ) -> None:
        """回归 + 文字类别结局 → 400，文案引导改用分类。"""
        version = await _make_version(db_session, researcher, _text_label_csv(), "reg_text")
        body = _body(version.id, ["lasso"])
        body["task_type"] = "regression"
        body["preprocess_config"] = _cfg({"label_col": "outcome"}, strategy="kfold")
        resp = await client.post("/api/v1/analysis-runs", json=body, headers=_auth(researcher))
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"
        msg = resp.json()["message"]
        assert "数值" in msg and "分类" in msg

    async def test_classification_rare_class_400(
        self, client: AsyncClient, db_session: AsyncSession, researcher: User
    ) -> None:
        """stratified_kfold 下最小类别样本数 < n_splits → 400，文案含类别/样本数/折数。"""
        version = await _make_version(db_session, researcher, _imbalanced_csv(), "imbalanced")
        body = _body(version.id, ["dummy"])  # CLF_CONFIG：stratified_kfold × 3
        resp = await client.post("/api/v1/analysis-runs", json=body, headers=_auth(researcher))
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"
        msg = resp.json()["message"]
        assert "2 例" in msg and "3" in msg and "分层" in msg

    async def test_label_column_missing_400(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        body = _body(version.id, ["dummy"])
        body["preprocess_config"] = _cfg({"label_col": "no_such_col"})
        resp = await client.post("/api/v1/analysis-runs", json=body, headers=_auth(researcher))
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"
        assert "不存在" in resp.json()["message"]

    async def test_survival_target_column_missing_400(
        self, client: AsyncClient, researcher: User, version: DatasetVersion
    ) -> None:
        """survival 的 time/event 列名笔误 → 400 存在性校验（先于插件校验）。"""
        body = _body(version.id, ["dummy"])
        body["task_type"] = "survival"
        body["preprocess_config"] = _cfg({"time_col": "t", "event_col": "e"}, strategy="kfold")
        resp = await client.post("/api/v1/analysis-runs", json=body, headers=_auth(researcher))
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"
        assert "不存在" in resp.json()["message"]


class TestRunQueries:
    async def _completed_run(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> str:
        resp = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
        )
        assert resp.status_code == 202
        db_session.expunge_all()  # worker 在独立会话更新 run；清缓存保证后续读到最新状态
        return str(resp.json()["id"])

    async def test_detail_and_progress(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await self._completed_run(client, db_session, researcher, version)

        detail = await client.get(f"/api/v1/analysis-runs/{run_id}", headers=_auth(researcher))
        assert detail.status_code == 200
        assert detail.json()["status"] == "COMPLETED"

        progress = await client.get(
            f"/api/v1/analysis-runs/{run_id}/progress", headers=_auth(researcher)
        )
        assert progress.status_code == 200
        body = progress.json()
        assert body["percent"] == 100
        assert body["models"] == {"dummy": "SUCCESS"}

    async def test_list_project_runs(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await self._completed_run(client, db_session, researcher, version)
        project_id = (await db_session.get(Dataset, version.dataset_id)).project_id

        resp = await client.get(
            f"/api/v1/projects/{project_id}/analysis-runs", headers=_auth(researcher)
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert run_id in ids

    async def test_cross_owner_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await self._completed_run(client, db_session, researcher, version)
        other = User(
            email="other@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()

        resp = await client.get(f"/api/v1/analysis-runs/{run_id}", headers=_auth(other))
        assert resp.status_code == 403

    async def test_not_found_404(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.get(f"/api/v1/analysis-runs/{uuid.uuid4()}", headers=_auth(researcher))
        assert resp.status_code == 404


class TestComparison:
    """T6.1：GET /analysis-runs/{id}/comparison（docs/14 ComparisonResult）。"""

    async def _create(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
        models: list[str],
        model_params: dict[str, dict[str, object]] | None = None,
    ) -> str:
        resp = await client.post(
            "/api/v1/analysis-runs",
            json=_body(version.id, models, model_params),
            headers=_auth(researcher),
        )
        assert resp.status_code == 202
        db_session.expunge_all()
        return str(resp.json()["id"])

    async def test_comparison_completed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await self._create(client, db_session, researcher, version, ["logreg", "dummy"])

        resp = await client.get(
            f"/api/v1/analysis-runs/{run_id}/comparison", headers=_auth(researcher)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert [row["model_key"] for row in body["table"]] == ["logreg", "dummy"]
        logreg = body["table"][0]
        assert logreg["status"] == "SUCCESS"
        assert set(logreg["metrics"]["auc"]) == {"mean", "std", "folds"}
        assert logreg["duration_ms"] is not None
        assert logreg["error"] is None
        assert body["ranking"]  # compare 已落库
        assert body["recommendation"]["primary_metric"] == "auc"
        # T6.2：compare 装配对比图表（dummy 无产物 → roc 等只含 logreg 系列）
        kinds = {c["kind"] for c in body["charts"]}
        assert {"roc", "calibration", "dca"} <= kinds
        roc = next(c for c in body["charts"] if c["kind"] == "roc")
        assert [s["model_key"] for s in roc["data"]["series"]] == ["logreg"]

    async def test_failed_model_annotated(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await self._create(
            client, db_session, researcher, version, ["logreg", "dummy"], {"logreg": {"C": -1.0}}
        )

        resp = await client.get(
            f"/api/v1/analysis-runs/{run_id}/comparison", headers=_auth(researcher)
        )
        assert resp.status_code == 200
        body = resp.json()
        logreg = next(r for r in body["table"] if r["model_key"] == "logreg")
        assert logreg["status"] == "FAILED"
        assert logreg["metrics"] is None  # 失败模型标注（T6.1 DoD）
        assert logreg["error"]
        assert body["ranking"] == ["dummy"]

    async def test_comparison_cross_owner_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        researcher: User,
        version: DatasetVersion,
    ) -> None:
        run_id = await self._create(client, db_session, researcher, version, ["dummy"])
        other = User(
            email="cmp-other@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.get(f"/api/v1/analysis-runs/{run_id}/comparison", headers=_auth(other))
        assert resp.status_code == 403

    async def test_comparison_not_found_404(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.get(
            f"/api/v1/analysis-runs/{uuid.uuid4()}/comparison", headers=_auth(researcher)
        )
        assert resp.status_code == 404
