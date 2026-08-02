"""T8.3 性能压测脚本（docs/19 §6；NFR：10w 行 × 50 列全链路 ≤ 10 min）。

在容器内以同步 eager 模式驱动真实 worker 链路（chord 顺序执行 = 并行下界），
逐阶段计时并对照 docs/19 §6 目标出 markdown 报告：

    docker run --rm --network cdap_default \
      -e TEST_DATABASE_URL=postgresql+psycopg://...@cdap-postgres-1:5432/cdap_test \
      -v .../backend:/app -w /app cdap-test:latest \
      bash -c "pip install -q --no-deps -e . && \
        python -m scripts.perf_benchmark --output /app/docs_perf_report.md"

场景覆盖：校验 ≤30s；全链路 ≤10min；PDF ≤60s；worker RSS < 2GB。
"""

import argparse
import hashlib
import io
import json
import os
import platform
import resource
import sys
import time

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("LOCAL_STORAGE_PATH", "./.perf_storage")
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

import numpy as np
import pandas as pd

TARGETS = {
    "validate_s": 30.0,
    "pipeline_s": 600.0,
    "report_s": 60.0,
    "rss_mb": 2048.0,
}

CLF_MODELS = ["logreg", "rf", "svm", "xgboost", "lightgbm", "catboost"]


def make_csv(rows: int, cols: int, seed: int = 42) -> bytes:
    """cols 含 label 列；45 连续 + 其余分类编码 + label（带信号，AUC>0.5 可学）。"""
    rng = np.random.default_rng(seed)
    n_cont = max(1, cols - 6)
    data: dict[str, object] = {}
    signal = np.zeros(rows)
    for i in range(n_cont):
        x = rng.normal(0, 1, rows)
        data[f"feat_{i:02d}"] = x
        if i < 5:
            signal += x
    for j in range(cols - 1 - n_cont):
        data[f"cat_{j}"] = rng.integers(0, 5, rows)
    prob = 1.0 / (1.0 + np.exp(-signal))
    data["label"] = (rng.random(rows) < prob).astype(int)
    return pd.DataFrame(data).to_csv(index=False).encode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--cols", type=int, default=50)
    ap.add_argument("--models", type=str, default=",".join(CLF_MODELS))
    ap.add_argument("--n-splits", type=int, default=3)
    ap.add_argument("--output", type=str, default="")
    args = ap.parse_args()
    models = [m for m in args.models.split(",") if m]

    # 延迟导入：env 须先于 app 配置加载
    from app.models.base import Base
    from app.models.entities import (
        AnalysisRun,
        Dataset,
        DatasetVersion,
        ModelPlugin,
        ModelResult,
        Project,
        Report,
        User,
    )
    from app.services.storage import storage_from_settings
    from app.workers import db as worker_db
    from app.workers.analysis_tasks import dispatch_analysis_run
    from app.workers.celery_app import celery_app
    from app.workers.dataset_tasks import validate_dataset
    from app.workers.report_tasks import generate_report
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    celery_app.conf.update(task_always_eager=True)
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    worker_db._factory = factory  # worker 任务指向压测库

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    csv_bytes = make_csv(args.rows, args.cols)
    timings["generate_csv"] = time.perf_counter() - t0
    size_mb = len(csv_bytes) / 1024 / 1024

    storage = storage_from_settings()
    t0 = time.perf_counter()
    uri = storage.put("datasets/perf/bench.csv", io.BytesIO(csv_bytes))
    timings["storage_put"] = time.perf_counter() - t0

    with factory() as db:
        # model_results FK → model_plugins：同步注册表（等价 sync_plugins_to_db，同步版）
        from app.api.deps import get_registry

        for registered in get_registry().all():
            adapter = registered.adapter
            db.add(
                ModelPlugin(
                    key=adapter.key,
                    name=adapter.name,
                    version=adapter.version,
                    task_types=list(adapter.task_types),
                    capability=dict(adapter.capabilities),
                    default_params=dict(adapter.default_params),
                    enabled=True,
                    entry_point=registered.entry_point,
                )
            )
        user = User(
            email="perf@example.com",
            password_hash="x",  # noqa: S106 压测占位，不做登录
            role="researcher",
            display_name="Perf",
        )
        db.add(user)
        db.flush()
        project = Project(owner_id=user.id, name="压测项目", description="")
        db.add(project)
        db.flush()
        dataset = Dataset(
            project_id=project.id,
            name="perf",
            source_type="csv",
            storage_uri=uri,
            file_hash=hashlib.sha256(csv_bytes).hexdigest(),
            file_size=len(csv_bytes),
            status="UPLOADED",
        )
        db.add(dataset)
        db.flush()
        version = DatasetVersion(
            dataset_id=dataset.id, version_no=1, storage_uri=uri, transform_log=[]
        )
        db.add(version)
        db.commit()

        t0 = time.perf_counter()
        validate_dataset(str(dataset.id))
        timings["validate"] = time.perf_counter() - t0
        db.refresh(dataset)
        assert dataset.status == "VALIDATED", f"校验未通过：{dataset.status}"

        config = {
            "target": {"label_col": "label"},
            "steps": [{"type": "scale", "params": {}}],
            "validation": {
                "strategy": "stratified_kfold",
                "n_splits": args.n_splits,
                "seed": 42,
            },
        }
        run = AnalysisRun(
            project_id=project.id,
            dataset_version_id=version.id,
            task_type="classification",
            status="PENDING",
            preprocess_config=config,
            selected_models=models,
            created_by=user.id,
        )
        db.add(run)
        db.commit()

        t0 = time.perf_counter()
        dispatch_analysis_run(str(run.id), models)
        timings["pipeline"] = time.perf_counter() - t0
        db.refresh(run)
        results = (
            db.execute(select(ModelResult).where(ModelResult.run_id == run.id)).scalars().all()
        )

        report = Report(run_id=run.id, format="pdf", created_by=user.id)
        db.add(report)
        db.commit()
        t0 = time.perf_counter()
        generate_report.apply_async(args=[str(report.id)])
        timings["report_pdf"] = time.perf_counter() - t0
        db.refresh(report)

        per_model = {
            r.model_key: {"status": r.status, "duration_ms": r.duration_ms} for r in results
        }
        run_status, report_status = run.status, report.status

    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    checks = {
        "校验 ≤ 30s": timings["validate"] <= TARGETS["validate_s"],
        "全链路 ≤ 10min": timings["pipeline"] <= TARGETS["pipeline_s"],
        "PDF ≤ 60s": timings["report_pdf"] <= TARGETS["report_s"],
        "RSS < 2GB": rss_mb <= TARGETS["rss_mb"],
        "运行完成": run_status == "COMPLETED",
        "报告 READY": report_status == "READY",
    }
    summary = {
        "rows": args.rows,
        "cols": args.cols,
        "csv_mb": round(size_mb, 1),
        "models": models,
        "n_splits": args.n_splits,
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
        "per_model": per_model,
        "rss_mb": round(rss_mb, 1),
        "run_status": run_status,
        "report_status": report_status,
        "checks": checks,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.output:

        def _verdict(ok: bool) -> str:
            return "PASS" if ok else "FAIL"

        stage_rows = [
            ("数据校验", f"{timings['validate']:.1f}s", "≤30s", checks["校验 ≤ 30s"]),
            (
                f"全链路（预处理+{len(models)} 模型+比较）",
                f"{timings['pipeline']:.1f}s",
                "≤600s",
                checks["全链路 ≤ 10min"],
            ),
            ("PDF 报告生成", f"{timings['report_pdf']:.1f}s", "≤60s", checks["PDF ≤ 60s"]),
            ("Worker RSS", f"{rss_mb:.0f}MB", "<2048MB", checks["RSS < 2GB"]),
            (f"上传落盘（{size_mb:.0f}MB）", f"{timings['storage_put']:.2f}s", "异步不阻塞", True),
        ]
        lines = [
            "# 性能压测报告（T8.3；docs/19 §6）",
            "",
            f"- 日期：{time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 环境：{platform.platform()}；CPU {os.cpu_count()} 核；"
            f"Python {platform.python_version()}",
            f"- 数据：{args.rows} 行 × {args.cols} 列合成分类集（CSV {size_mb:.1f}MB，seed=42）",
            f"- 模型：{', '.join(models)}；CV={args.n_splits} 折（eager 顺序执行 = 并行耗时上界）",
            "",
            "## 阶段耗时",
            "",
            "| 阶段 | 实测 | 目标 | 结论 |",
            "|---|---|---|---|",
            *[
                f"| {name} | {got} | {target} | {_verdict(ok)} |"
                for name, got, target, ok in stage_rows
            ],
            "",
            "## 每模型耗时",
            "",
            "| 模型 | 状态 | 耗时 |",
            "|---|---|---|",
        ]
        for key, info in per_model.items():
            ms = info["duration_ms"] or 0
            lines.append(f"| {key} | {info['status']} | {ms / 1000:.1f}s |")
        lines += [
            "",
            f"运行状态：{run_status}；报告状态：{report_status}。",
            "注：SVM 拟合/SHAP/permutation 已按 docs/07 §6.1 大样本保护子采样；",
            "指标在全量验证折计算。",
        ]
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
