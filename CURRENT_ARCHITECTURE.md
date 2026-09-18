# Current Architecture

## Scope
本文件记录 CDAP 在 V2.0 P0 升级开始前的真实架构基线，依据当前工作树源码与容器运行约定整理。

## Runtime Flow
1. FastAPI 接收项目、数据集、分析运行与报告请求。
2. 数据集上传后写入 Local/S3 storage，Celery `validate_dataset` 解析文件并调用 `engines.validation`，结果落库 `QualityReport`。
3. `auto_dataset_insight` 生成 EDA、任务候选、研究画像和补充建议。
4. `services.analysis.create_run` 校验目标列、预处理 DSL 和插件，创建 `AnalysisRun`。
5. `preprocess_run` 读取原始文件，执行最终预处理并把 `raw_features`、`features`、`target` 和快照写入对象存储。
6. Celery chord 为每个模型执行 CV。每个 fold 重建 sklearn Pipeline，在训练折 fit、验证折 transform；然后保存指标、OOF/图表/解释性产物。
7. `compare_run` 汇总成功模型，执行排名、图表和比较结果，完成运行并排队报告。
8. `report_tasks.generate_report` 从 DB + 对象存储组装 payload，构造 ReportContext，生成 HTML/PDF/Markdown/DOCX。
9. 报告解释路径使用确定性 facts 调用 Ollama；LLM 只生成文字，数值由 validator 和事实绑定约束。

## Existing Strengths
- 分层已基本形成：API → services → workers → engines/plugins。
- 模型指标集中在 `engines/comparison/metrics.py`，分类已有 AUC、Brier、PR-AUC 等。
- CV 已有 fold 内重新 fit Pipeline 的基本模式。
- 报告有固定免责声明、红旗检测和单一事实源。
- 本地 Ollama、云端开关和规则/模板回退已存在。

## P0 Risk Boundaries
- 没有独立、可执行的 target/proxy/patient/temporal leakage engine 和分析前门禁。
- validation 只有普通 KFold/StratifiedKFold，不能按患者或时间隔离。
- >100k 行采样使用普通 `df.sample`，未保证阳性、患者组、时间边界。
- QualityReport 的 blocker 尚未统一转化为 analysis run 的方法学 gate。
- EPV 仅是 EDA/报告层粗略估计，未按实际候选变量与运行策略统一检查。
- `time_series` 在 schema/DB 有枚举，但 worker、metrics、ranking、report 未完整实现。
- 校准、PR-AUC 和分类指标有局部实现，但尚未全部以明确字段和报告门禁形式暴露。
- 报告可在 LLM 分节失败后继续 READY，需显示解释来源和降级状态。

## P0 Target Architecture
`upload → quality gate → research question/target → leakage & prediction-time gate → analysis plan → group/time-aware CV → deterministic metrics → integrity review → report`

P0 变更必须保持 engines 不依赖 FastAPI/Celery/SQLAlchemy ORM，所有数值由确定性引擎计算，LLM 只解释已绑定 facts。
