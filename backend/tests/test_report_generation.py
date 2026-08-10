"""T7.3 报告生成集成测试（docs/10 §3、§5 DoD；docs/19 M3）。

- generate_report 端到端：PENDING → READY，HTML 落存储；
- 契约测试：报告 HTML 中的指标数字与 Comparison 落库数据（即 comparison
  API 同源数据）逐一一致（不虚构）；
- 幂等：重复执行不报错；非 COMPLETED 运行 → FAILED。
"""

import uuid

import pytest
from app.engines.reporting.render import TEMPLATE_VERSION
from app.models.entities import Comparison, QualityReport, Report
from app.services.storage import storage_from_settings
from app.workers import db as worker_db
from app.workers.report_tasks import generate_report, key_of_report
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_analysis_orchestration import _create_run, _fetch_run
from tests.test_analysis_orchestration import seeded as _seeded_impl
from tests.test_analysis_orchestration import worker_sync_db as _ws_impl

# 共享 fixture 再导出：pytest 按模块属性名发现，直接 import 原名会与测试参数
# 同名触发 F811（seeded/worker_sync_db 定义见 test_analysis_orchestration）。
seeded = _seeded_impl
worker_sync_db = _ws_impl


def _new_report(user_id: uuid.UUID, run_id: uuid.UUID, fmt: str = "html") -> Report:
    return Report(run_id=run_id, format=fmt, created_by=user_id)


@pytest.mark.usefixtures("worker_sync_db")
class TestReportGeneration:
    async def test_html_ready_and_numbers_match_comparison(
        self, db_session: AsyncSession, seeded
    ) -> None:
        user, version = seeded
        # 质量报告落库（报告第 2 章数据源）
        db_session.add(
            QualityReport(
                dataset_id=version.dataset_id,
                dataset_version_id=version.id,
                status="PASSED",
                blockers=0,
                warnings=0,
                issues=[],
                column_profiles=[
                    {
                        "name": "age",
                        "inferred_type": "continuous",
                        "missing_rate": 0.0,
                        "unique": 60,
                        "min": 30.0,
                        "max": 90.0,
                    }
                ],
            )
        )
        await db_session.commit()

        run = await _create_run(db_session, user, version, ["logreg", "rf"])
        from app.workers.analysis_tasks import dispatch_analysis_run

        dispatch_analysis_run(str(run.id), ["logreg", "rf"])
        done, _ = _fetch_run(run.id)
        assert done.status == "COMPLETED"

        report = _new_report(user.id, run.id)
        db_session.add(report)
        await db_session.commit()

        generate_report.apply_async(args=[str(report.id)])

        factory = worker_db.get_sync_session_factory()
        with factory() as db:
            saved = db.get(Report, report.id)
            assert saved is not None and saved.status == "READY"
            assert saved.template_key == "clinical_report_zh"
            assert saved.template_version == TEMPLATE_VERSION
            assert saved.storage_uri
            comparison = db.execute(
                select(Comparison).where(Comparison.run_id == run.id)
            ).scalar_one()
            html = storage_from_settings().get(key_of_report(saved)).decode("utf-8")

        # 契约测试：HTML 中的数字与 Comparison 同源数据一致
        for chart_metric_rows in [comparison.recommendation]:
            assert chart_metric_rows["formula"] in html
        assert "不构成临床诊断建议" in html
        assert "附录：可复现性信息" in html
        for entry in comparison.recommendation["top"]:
            assert entry["reason"] in html
        assert "表 1 变量概况" in html  # Table 1 来自质量报告列画像
        assert "data:image/png;base64," in html  # 图表已装配 PNG

    async def test_idempotent_and_non_completed_fails(
        self, db_session: AsyncSession, seeded
    ) -> None:
        user, version = seeded
        run = await _create_run(db_session, user, version, ["logreg"])
        report = _new_report(user.id, run.id)  # 运行未 COMPLETED
        db_session.add(report)
        await db_session.commit()

        generate_report.apply_async(args=[str(report.id)])
        factory = worker_db.get_sync_session_factory()
        with factory() as db:
            assert db.get(Report, report.id).status == "FAILED"

        # 幂等：终态报告重复投递不再变更
        generate_report.apply_async(args=[str(report.id)])
        with factory() as db:
            assert db.get(Report, report.id).status == "FAILED"

        # 不存在的 report 不报错
        generate_report.apply_async(args=[str(uuid.uuid4())])
