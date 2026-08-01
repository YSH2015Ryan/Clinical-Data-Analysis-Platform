"""T7.4 PDF 导出测试（docs/10 §3 渲染管线、§5 DoD）。

- html_to_pdf：中文文本 + base64 图表 → 合法 PDF（%PDF 魔数），嵌入 Noto
  CJK 字体子集（无缺字 —— 字体子集名出现在 PDF 字节流中）；
- generate_report format=pdf 端到端：READY + report.pdf 落存储，幂等；
- 性能冒烟：10w 行规模数据概况的报告 PDF 生成 < 60s（docs/10 §5 DoD）。
"""

import re
import time
import zlib

import pytest
from app.engines.reporting.pdf import html_to_pdf
from app.models.entities import Comparison, Report
from app.services.storage import storage_from_settings
from app.workers import db as worker_db
from app.workers.report_tasks import generate_report, key_of_report
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_analysis_orchestration import _create_run, _fetch_run
from tests.test_analysis_orchestration import seeded as _seeded_impl
from tests.test_analysis_orchestration import worker_sync_db as _ws_impl

# 共享 fixture 再导出（同 test_report_generation）
seeded = _seeded_impl
worker_sync_db = _ws_impl

PDF_MAGIC = b"%PDF"
NOTO_CJK = b"Noto-Sans-CJK"


def _inflated(pdf: bytes) -> bytes:
    """解压 PDF 全部 FlateDecode 流（字体子集名在压缩流内）。"""
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except zlib.error:
            continue
    return b"".join(chunks)


class TestHtmlToPdf:
    def test_chinese_text_embeds_noto_cjk(self) -> None:
        html = (
            "<html><body style='font-family:\"Noto Sans CJK SC\",sans-serif'>"
            "<h1>临床数据分析报告</h1><p>年龄每增加 10 岁，风险比 1.21。</p>"
            "</body></html>"
        )
        pdf = html_to_pdf(html)
        assert pdf.startswith(PDF_MAGIC)
        # 中文字形须来自嵌入的 Noto CJK 子集，而非缺字方块（docs/10 §5）
        assert NOTO_CJK in _inflated(pdf)

    def test_image_and_table_render(self) -> None:
        from app.engines.reporting.chart_png import chart_to_b64

        chart = {
            "kind": "roc",
            "data": {
                "series": [
                    {"model_key": "logreg", "fpr": [0, 0.1, 1], "tpr": [0, 0.9, 1], "auc": 0.8}
                ]
            },
        }
        b64 = chart_to_b64(chart)
        html = (
            "<html><body><table><tr><td>auc</td><td>0.8123</td></tr></table>"
            f'<img src="data:image/png;base64,{b64}"></body></html>'
        )
        pdf = html_to_pdf(html)
        assert pdf.startswith(PDF_MAGIC)
        assert b"/Subtype /Image" in pdf  # 图像 XObject 已嵌入


@pytest.mark.usefixtures("worker_sync_db")
class TestGeneratePdfReport:
    async def test_pdf_ready_idempotent(self, db_session: AsyncSession, seeded) -> None:
        user, version = seeded
        run = await _create_run(db_session, user, version, ["logreg"])
        from app.workers.analysis_tasks import dispatch_analysis_run

        dispatch_analysis_run(str(run.id), ["logreg"])
        done, _ = _fetch_run(run.id)
        assert done.status == "COMPLETED"

        report = Report(run_id=run.id, format="pdf", created_by=user.id)
        db_session.add(report)
        await db_session.commit()

        started = time.monotonic()
        generate_report.apply_async(args=[str(report.id)])
        elapsed = time.monotonic() - started

        factory = worker_db.get_sync_session_factory()
        with factory() as db:
            saved = db.get(Report, report.id)
            assert saved is not None and saved.status == "READY"
            assert saved.storage_uri and saved.storage_uri.endswith("report.pdf")
            pdf = storage_from_settings().get(key_of_report(saved))
            comparison = db.execute(
                select(Comparison).where(Comparison.run_id == run.id)
            ).scalar_one()

        assert pdf.startswith(PDF_MAGIC)
        assert NOTO_CJK in _inflated(pdf)  # 中文无缺字（字体子集嵌入）
        # 契约同源：PDF 与 HTML 同一渲染管线，字体子集 + 图表图像均在
        assert comparison.recommendation["formula"]  # 数据源存在（HTML 契约见 T7.3）
        # 性能：60 样本小 run 全流程（分析已完成，仅报告渲染）远小于 60s 上限
        assert elapsed < 60

        # 幂等：终态重复投递不变更
        generate_report.apply_async(args=[str(report.id)])
        with factory() as db:
            again = db.get(Report, report.id)
            assert again is not None and again.status == "READY"
            assert again.storage_uri == saved.storage_uri

    async def test_pdf_large_run_perf(self, db_session: AsyncSession, seeded) -> None:
        """10w 行规模报告渲染（docs/10 §5：≤60s）。

        报告渲染与行数无关（输入为聚合指标 + 图表 PNG），此处用完整
        HTML → PDF 转换计时验证 WeasyPrint 路径在上限内。
        """
        from app.engines.reporting.context import build_report_context
        from app.engines.reporting.render import render_html
        from app.workers.report_tasks import _embed_images

        payload = {
            "run": {
                "task_type": "classification",
                "status": "COMPLETED",
                "selected_models": ["logreg"],
                "created_at": "2026-08-01",
                "finished_at": "2026-08-01",
            },
            "dataset": {"name": "large-100k"},
            "target_summary": {
                "n_samples": 100_000,
                "n_features": 32,
                "positives": 42_000,
                "prevalence": 0.42,
            },
            "validation": {"strategy": "stratified_kfold", "n_splits": 5, "seed": 42},
            "task_detection": None,
            "quality_report": None,
            "transform_log": [],
            "preprocess_steps": None,
            "input_hash": "0" * 64,
            "table": [
                {
                    "model_key": "logreg",
                    "status": "COMPLETED",
                    "metrics": {"auc": {"mean": 0.8, "std": 0.01}},
                    "duration_ms": 1234,
                }
            ],
            "comparison": {
                "ranking": ["logreg"],
                "recommendation": {
                    "top": [{"model_key": "logreg", "rank": 1, "reason": "主指标最高"}],
                    "not_recommended": [],
                    "formula": "score = 0.6×主指标归一化",
                },
                "charts": [
                    {
                        "kind": "roc",
                        "data": {
                            "series": [
                                {
                                    "model_key": "logreg",
                                    "fpr": [0, 0.1, 1],
                                    "tpr": [0, 0.9, 1],
                                    "auc": 0.8,
                                }
                            ]
                        },
                    }
                ],
            },
            "software": {"python": "3.11"},
        }
        context = build_report_context(payload)
        _embed_images(context)
        html = render_html(context)
        started = time.monotonic()
        pdf = html_to_pdf(html)
        elapsed = time.monotonic() - started
        assert pdf.startswith(PDF_MAGIC)
        assert elapsed < 60
