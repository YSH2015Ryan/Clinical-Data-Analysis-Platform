"""阶段 A 数据体检任务（P1-1/P2-2，docs/08 §3.2）：校验成功后自动续跑。

流程：
  1. 安全项自动修复（impute_missing / winsorize_outliers / to_missing）——
     quickfix 全部生成新 DatasetVersion（源文件不可变 ⇒ 可自动执行）；
     不可逆类（drop_column / drop_rows_* / pivot / rename / remap /
     normalize_units / drop_duplicates）只建议不自动执行；
     每次修复后同步重校验；不再有可自动修复项即停止（最多 3 轮防环）。
  2. EDA 引擎（engines/eda.py，纯计算）产出分布/缺失/相关性/EPV。
  3. 规则任务推荐（IntelligentTaskAdvisor switch="off"：LLM 表达增强已在
     validate_dataset 写入 QualityReport，此处只保留确定性规则结论）。
  4. 研究画像（engines/research_profiler，规则产出）。
  5. 落库 DatasetInsight（替换旧记录，幂等）；前端数据集页直接渲染。

红线 8：payload 全部数值来自引擎真实计算，无任何编造。
"""

import io
import uuid
from dataclasses import asdict
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, select

from app.core.logging import get_logger
from app.engines import parser, quickfix, validation
from app.engines.eda import compute_eda
from app.engines.intelligent_task_advisor import IntelligentTaskAdvisor
from app.engines.research_profiler import detect_research_direction
from app.engines.supplement_advisor import advise_supplements
from app.models.entities import Dataset, DatasetInsight, DatasetVersion, QualityReport
from app.services.storage import StorageBackend, key_from_uri, storage_from_settings
from app.workers.celery_app import celery_app
from app.workers.db import get_sync_session_factory

logger = get_logger(__name__)

_MAX_FIX_ROUNDS = 3

# 可自动修复的安全项映射：rule_id(+severity) → 动作构造器
# RV201 仅 warning 级自动插补（blocker 级缺失率过高，插补在统计上不可靠，留给用户决策）；
# RV301 虽为 blocker，但 to_missing 语义即该校验项的建议动作且生成新版本可回溯。
_FIXABLE: dict[tuple[str, str], str] = {
    ("RV201", "warning"): "impute_missing",
    ("RV301", "blocker"): "to_missing",
    ("RV501", "warning"): "winsorize_outliers",
    ("RV804", "warning"): "winsorize_outliers",
}


def _safe_auto_fixes(issues: list[dict[str, Any]]) -> list[quickfix.QuickFixAction]:
    actions: list[quickfix.QuickFixAction] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        rule_id = issue.get("rule_id")
        severity = issue.get("severity")
        if not isinstance(rule_id, str) or not isinstance(severity, str):
            continue
        action_type = _FIXABLE.get((rule_id, severity))
        column = issue.get("column")
        if action_type is None or not column or (action_type, column) in seen:
            continue
        seen.add((action_type, column))
        params = {"strategy": "auto"} if action_type == "impute_missing" else {}
        actions.append(quickfix.QuickFixAction(type=action_type, column=column, params=params))
    return actions


def _persist_fixed_version(
    db: Any,
    storage: StorageBackend,
    dataset: Dataset,
    df: pd.DataFrame,
    transform_log: list[dict[str, Any]],
) -> DatasetVersion:
    """同步版 quickfix 服务：写新存储对象 + DatasetVersion + 重校验刷新展示状态。"""
    version_no = (
        int(
            db.execute(
                select(func.coalesce(func.max(DatasetVersion.version_no), 0)).where(
                    DatasetVersion.dataset_id == dataset.id
                )
            ).scalar_one()
        )
        + 1
    )
    safe_name = dataset.name.replace("/", "_").replace("\\", "_")[-120:]
    key = f"datasets/{dataset.project_id}/{dataset.id}/v{version_no}/{safe_name}"
    buf = io.BytesIO()
    if dataset.source_type == "excel":
        df.to_excel(buf, index=False)
    else:
        buf.write(df.to_csv(index=False).encode("utf-8"))
    size = buf.tell()
    buf.seek(0)
    uri = storage.put(key, buf, size)

    version = DatasetVersion(
        dataset_id=dataset.id, version_no=version_no, storage_uri=uri, transform_log=transform_log
    )
    db.add(version)
    db.flush()

    report = validation.validate(df, raw_columns=[str(c) for c in df.columns])
    dataset.storage_uri = uri
    dataset.preview = parser.preview_json(df)
    dataset.column_profile = parser.normalize_json_value(report.column_profiles)
    dataset.status = "FAILED" if report.status == "FAILED" else "VALIDATED"
    if dataset.source_type == "csv":
        dataset.encoding = "utf-8"
    db.add(
        QualityReport(
            dataset_id=dataset.id,
            dataset_version_id=version.id,
            status=report.status,
            blockers=report.blockers,
            warnings=report.warnings,
            issues=[i.to_dict() for i in report.issues],
            column_profiles=parser.normalize_json_value(report.column_profiles),
        )
    )
    db.commit()
    return version


def _summary_lines(
    eda: dict[str, Any],
    recommendation: Any,
    research: dict[str, Any],
    auto_fix_log: list[dict[str, Any]],
    report: validation.ValidationReport,
) -> list[str]:
    """体检结论文案：全部引用真实计算数值（红线 8）。"""
    lines: list[str] = []
    ss = eda["sample_size"]
    lines.append(f"数据集共 {eda['row_count']} 行、{eda['column_count']} 列。")
    if auto_fix_log:
        fixed = sorted(
            {f"{e['column']}（{e['action']}，{e['affected_rows']} 行）" for e in auto_fix_log}
        )
        lines.append(
            f"已自动修复 {len(auto_fix_log)} 项：{'、'.join(fixed)}；源文件保持不变，可随时回溯。"
        )
    if report.blockers:
        lines.append(f"仍有 {report.blockers} 项阻塞级问题需人工处理后方可建模。")
    if ss.get("n_events") is not None:
        # updateplan §19 三档分级文案（epv_level 由 eda 确定性计算）
        level_text = {
            "ok": "（≥10，满足常规建模要求）",
            "warning": "（5–10，偏低：建议精简候选特征或扩充样本，结果按探索性解读）",
            "critical": "（<5，严重不足：模型系数不稳定、性能指标易虚高，本次分析仅宜作探索性用途）",
        }
        lines.append(
            f"结局事件列 {ss['event_column']}：事件数 {ss['n_events']}，EPV={ss['epv']}"
            + level_text.get(ss.get("epv_level") or "", "")
        )
    missing = eda["missing"]
    lines.append(f"完整病例比例 {missing['complete_case_ratio']:.1%}。")
    if recommendation.recommended_tasks:
        lines.append(
            f"推荐任务：{'、'.join(recommendation.recommended_tasks)}"
            f"（{recommendation.overall_assessment}）"
        )
    else:
        lines.append("未识别出可直接建模的结局列，建议先做探索性分析或补充结局变量。")
    lines.append(
        f"研究设计画像：{research['research_type']}（置信度 {research['confidence']}）；"
        f"推荐模型 {', '.join(research['recommended_models'])}。"
    )
    return lines


@celery_app.task(name="app.workers.insight_tasks.auto_dataset_insight")
def auto_dataset_insight(dataset_id: str) -> None:
    session_factory = get_sync_session_factory()
    with session_factory() as db:
        dataset = db.execute(
            select(Dataset).where(Dataset.id == uuid.UUID(dataset_id))
        ).scalar_one_or_none()
        if dataset is None:
            logger.warning("auto_insight_not_found", dataset_id=dataset_id)
            return
        if dataset.status == "FAILED":
            logger.info("auto_insight_skip_failed", dataset_id=dataset_id)
            return
        version = db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset.id)
            .order_by(DatasetVersion.version_no.desc())
            .limit(1)
        ).scalar_one_or_none()
        if version is None:
            logger.error("auto_insight_no_version", dataset_id=dataset_id)
            return

        storage = storage_from_settings()
        try:
            raw = storage.get(key_from_uri(dataset.storage_uri))
            result = parser.parse(raw, dataset.source_type)
        except Exception as exc:
            logger.error(
                "auto_insight_parse_failed", dataset_id=dataset_id, error=type(exc).__name__
            )
            return
        df = result.df

        # 1. 安全项自动修复循环（修复 → 重校验 → 直至无可修复项）
        auto_fix_log: list[dict[str, Any]] = []
        report = validation.validate(df, raw_columns=[str(c) for c in df.columns])
        for _ in range(_MAX_FIX_ROUNDS):
            actions = _safe_auto_fixes([i.to_dict() for i in report.issues])
            if not actions:
                break
            df, log = quickfix.apply_actions(df, actions)
            auto_fix_log.extend(log)
            version = _persist_fixed_version(db, storage, dataset, df, log)
            report = validation.validate(df, raw_columns=[str(c) for c in df.columns])
            logger.info(
                "auto_insight_fix_round",
                dataset_id=dataset_id,
                actions=[a.type for a in actions],
                blockers=report.blockers,
                warnings=report.warnings,
            )

        # 2-4. EDA + 任务推荐（规则）+ 研究画像 + 数据缺口建议(T6.14,确定性规则)
        eda = compute_eda(df, report.column_profiles)
        recommendation = IntelligentTaskAdvisor().analyze_dataset(
            df, report.column_profiles, switch="off"
        )
        research = detect_research_direction(df)
        supplement_plan = advise_supplements(df, eda, report.column_profiles, research)

        # 5. 落库（替换旧 insight，幂等）
        summary = _summary_lines(eda, recommendation, research, auto_fix_log, report)
        if supplement_plan["items"]:
            summary.append(supplement_plan["overall"])
        payload = {
            "eda": eda,
            "task_recommendation": asdict(recommendation),
            "research_profile": research,
            "auto_fix_log": auto_fix_log,
            "summary": summary,
            "supplement_plan": supplement_plan,
        }
        db.execute(delete(DatasetInsight).where(DatasetInsight.dataset_id == dataset.id))
        db.add(
            DatasetInsight(dataset_id=dataset.id, dataset_version_id=version.id, payload=payload)
        )
        db.commit()
        logger.info(
            "auto_insight_done",
            dataset_id=dataset_id,
            fixes=len(auto_fix_log),
            blockers=report.blockers,
            recommended=recommendation.recommended_tasks,
        )
