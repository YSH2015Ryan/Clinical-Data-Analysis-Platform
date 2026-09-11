"""T6.3/T6.4 报告增强接线测试（docs/10 §2-3；路线图 T6.3/T6.4）。

- OOF 预测持久化：run_model 成功后 runs/{id}/oof_{model}.parquet 存在且完整；
- T6.4：性能表按 comparison.ranking 排序，首行「参考」，其余带配对检验 p 值；
- T6.3 分类：基线特征表（Table 1 分层 + p 值）、Hosmer-Lemeshow 校准、
  Youden 最优阈值进报告；
- T6.3 回归：OOF 残差诊断（Shapiro/BP/DW/VIF）+ OLS 系数表进报告，
  系数值与数据真实关系一致（不虚构）。
"""

import io
import uuid

import numpy as np
import pandas as pd
import pytest
from app.core.security import hash_password
from app.models.entities import AnalysisRun, Comparison, Dataset, DatasetVersion, Project, User
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.auth import CurrentUser
from app.services import analysis as analysis_service
from app.services.storage import storage_from_settings
from app.workers import db as worker_db
from app.workers.analysis_tasks import dispatch_analysis_run
from app.workers.report_tasks import assemble_report_payload, render_report_html
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_analysis_orchestration import _create_run, _fetch_run, _registry
from tests.test_analysis_orchestration import seeded as _seeded_impl
from tests.test_analysis_orchestration import worker_sync_db as _ws_impl

seeded = _seeded_impl
worker_sync_db = _ws_impl

REG_CONFIG = {
    "target": {"label_col": "y"},
    "steps": [{"type": "scale", "params": {}}],
    "validation": {"strategy": "kfold", "n_splits": 3, "seed": 42},
}


def _reg_csv() -> bytes:
    rng = np.random.default_rng(7)
    n = 90
    age = rng.normal(60, 10, n)
    biomarker = rng.normal(0, 1, n)
    y = 20 + 0.5 * age + 3.0 * biomarker + rng.normal(0, 2.0, n)
    return pd.DataFrame({"age": age, "biomarker": biomarker, "y": y}).to_csv(index=False).encode()


@pytest.fixture()
async def seeded_reg(db_session: AsyncSession) -> tuple[User, DatasetVersion]:
    storage = storage_from_settings()
    uri = storage.put("datasets/test/reg.csv", io.BytesIO(_reg_csv()))
    user = User(
        email="reg@example.com",
        password_hash=hash_password("reg-pass"),
        role="researcher",
        display_name="Reg",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(owner_id=user.id, name="回归项目", description="")
    db_session.add(project)
    await db_session.flush()
    dataset = Dataset(
        project_id=project.id,
        name="reg",
        source_type="csv",
        storage_uri=uri,
        file_hash="1" * 64,
        file_size=1,
        status="VALIDATED",
    )
    db_session.add(dataset)
    await db_session.flush()
    version = DatasetVersion(dataset_id=dataset.id, version_no=1, storage_uri=uri, transform_log=[])
    db_session.add(version)
    await db_session.commit()
    return user, version


async def _create_reg_run(
    db_session: AsyncSession, user: User, version: DatasetVersion, models: list[str]
) -> AnalysisRun:
    body = AnalysisRunCreate(
        dataset_version_id=version.id,
        task_type="regression",
        preprocess_config=REG_CONFIG,
        selected_models=models,
        model_params={},
    )
    caller = CurrentUser(id=user.id, email=str(user.email), role=user.role)
    run = await analysis_service.create_run(db_session, caller, body, registry=_registry())
    await db_session.commit()
    return run


def _payload(run: AnalysisRun) -> dict:
    factory = worker_db.get_sync_session_factory()
    with factory() as db:
        return assemble_report_payload(db, run)


def _html(run: AnalysisRun) -> str:
    factory = worker_db.get_sync_session_factory()
    with factory() as db:
        return render_report_html(db, run)


def _ranking(run_id: uuid.UUID) -> list[str]:
    factory = worker_db.get_sync_session_factory()
    with factory() as db:
        comparison = db.execute(select(Comparison).where(Comparison.run_id == run_id)).scalar_one()
        return list(comparison.ranking)


@pytest.mark.usefixtures("worker_sync_db")
class TestReportWiringClassification:
    async def test_oof_persisted_and_table_sorted_with_pvalues(
        self, db_session: AsyncSession, seeded
    ) -> None:
        user, version = seeded
        run = await _create_run(db_session, user, version, ["logreg", "rf"])
        dispatch_analysis_run(str(run.id), ["logreg", "rf"])
        done, _ = _fetch_run(run.id)
        assert done.status == "COMPLETED"

        # OOF 落存储（T6.3 报告诊断数据源；二分类 → 单列正类概率）
        storage = storage_from_settings()
        for key in ("logreg", "rf"):
            oof = pd.read_parquet(io.BytesIO(storage.get(f"runs/{run.id}/oof_{key}.parquet")))
            assert list(oof.columns) == ["oof"]
            assert len(oof) == 60
            assert oof["oof"].notna().all()
            assert oof["oof"].between(0, 1).all()

        # T6.4：性能表按排名排序；首行参考，其余带配对检验 p 值
        ranking = _ranking(run.id)
        payload = _payload(done)
        table = payload["table"]
        assert [r["model_key"] for r in table] == ranking
        assert table[0]["p_value_text"] == "参考"
        assert table[0]["p_value"] is None
        assert table[1]["p_value"] is not None
        assert table[1]["p_value_text"]
        assert payload["significance_note"]

    async def test_baseline_table_and_calibration_in_report(
        self, db_session: AsyncSession, seeded
    ) -> None:
        user, version = seeded
        run = await _create_run(db_session, user, version, ["logreg", "rf"])
        dispatch_analysis_run(str(run.id), ["logreg", "rf"])
        done, _ = _fetch_run(run.id)
        assert done.status == "COMPLETED"

        payload = _payload(done)
        # 基线特征表：二分类按 label 分层，组间差异真实可检（label 由 age/biomarker 生成）
        bt = payload["baseline_table"]
        assert bt is not None and bt["rows"]
        assert bt["total_n"] == 60
        assert len(bt["strata"]) == 2
        assert any(r.get("p_value_text") not in (None, "", "—") for r in bt["rows"])
        # 校准：HL 检验 + Youden 最优阈值（基于推荐模型 OOF 概率）
        cal = payload["calibration"]
        assert cal is not None
        assert cal["model_key"] == _ranking(run.id)[0]
        assert cal["hosmer_lemeshow"]["conclusion"]
        assert cal["optimal_threshold"]["threshold"] is not None

        html = _html(done)
        assert "基线特征表" in html
        assert "Hosmer-Lemeshow" in html
        assert "Youden" in html
        assert "p 值(vs 最佳)" in html


@pytest.mark.usefixtures("worker_sync_db")
class TestReportWiringRegression:
    async def test_regression_diagnostics_in_report(
        self, db_session: AsyncSession, seeded_reg
    ) -> None:
        user, version = seeded_reg
        run = await _create_reg_run(db_session, user, version, ["lasso", "elasticnet"])
        dispatch_analysis_run(str(run.id), ["lasso", "elasticnet"])
        done, _ = _fetch_run(run.id)
        assert done.status == "COMPLETED"

        payload = _payload(done)
        ranking = _ranking(run.id)
        d = payload["diagnostics"]
        assert d is not None
        assert d["model_key"] == ranking[0]
        assert d["shapiro"]["conclusion"]
        assert d["breusch_pagan"] is not None
        assert d["durbin_watson"]["statistic"] is not None
        assert d["vif"]["max_vif"] is not None
        # OLS 系数表：全量数据 + 预处理特征空间；age 真实关系为正且显著
        assert d["coefficients"]
        assert d["coefficients"][0]["term"] == "(截距)"
        age_row = next(c for c in d["coefficients"] if c["term"] == "age")
        assert age_row["coef"] > 0
        assert age_row["p_value"] < 0.05
        assert age_row["ci_lower"] < age_row["ci_upper"]

        # T6.4：回归主指标 rmse 的 p 值列同样接线
        table = payload["table"]
        assert [r["model_key"] for r in table] == ranking
        assert table[0]["p_value_text"] == "参考"
        assert table[1]["p_value"] is not None

        html = _html(done)
        assert "回归诊断" in html
        assert "OLS 回归系数" in html
        assert "Shapiro-Wilk" in html
        assert "多重共线性" in html
        # 回归基线表无分层：仅总体统计
        assert "基线特征表" in html
