# Clinical Data Analysis Platform (CDAP) — 开发蓝图

> 版本：v1.0  | 日期：2026-07-28 | 状态：Planning Complete（待 Architecture Review Gate 通过）

## 这是什么

本目录是**临床数据分析平台（CDAP）**的完整开发计划（Development Blueprint），基于 `DVPlan.md` 中的 Vibe Coding 规划提示词编写。本阶段**不写代码**，只输出可直接指导后续 Coding Agent 一次性实现的架构设计、技术调研、任务拆解、风险分析与开发计划。

## 平台一句话定义

> 用户上传一份临床 CSV，平台自动完成：数据校验 → 数据预处理 → 自动识别分析任务 → 多模型并行分析 → 模型比较与推荐 → 生成一份真正的临床分析报告（PDF/HTML/Markdown/Word）。

平台**不重新训练/发明模型**，而是复用 GitHub 成熟开源项目（ehrapy、lifelines、scikit-survival、pycox/DeepSurv、XGBoost/LightGBM/CatBoost、SHAP 等）。

## 目标用户

- 科研人员、医生、医院、医学研究人员
- **不会编程**，全部通过 Web GUI 操作

## 文档导航（阅读顺序）

| 阶段 | 文档 | 内容 |
|---|---|---|
| Phase 1 需求分析 | [00-Project-Overview](00-Project-Overview.md) / [01-Business-Requirements](01-Business-Requirements.md) | 背景目标、用户角色、业务流程、功能与非功能需求 |
| Phase 2 调研 | [16-GitHub-Projects-Research](16-GitHub-Projects-Research.md) | ehrapy / ClinicoPath 等开源项目复用分析 |
| Phase 3 架构 | [02-System-Architecture](02-System-Architecture.md) / [03-Technology-Stack](03-Technology-Stack.md) | 总体架构图、模块架构、技术选型 |
| Phase 4 模块拆分 | [05](05-Data-Validation.md)/[06](06-Preprocessing-Pipeline.md)/[07](07-ML-Model-Management.md)/[08](08-Analysis-Workflow.md)/[09](09-Model-Comparison.md)/[10](10-Report-System.md)/[15](15-Plugin-System.md) | 每个模块的职责/输入/输出/依赖/接口/复杂度/风险 |
| Phase 5 数据库 | [04-Data-Model](04-Data-Model.md) / [13-Database-Design](13-Database-Design.md) | ER 图、数据表、字段、索引 |
| Phase 6 API | [14-API-Specification](14-API-Specification.md) | REST API + OpenAPI 规范 + 错误码 |
| Phase 7 ML Pipeline | [06](06-Preprocessing-Pipeline.md) / [08-Analysis-Workflow](08-Analysis-Workflow.md) | CSV→报告全链路流水线 |
| Phase 8 前端 | [11-Frontend-Design](11-Frontend-Design.md) | 页面、流程、组件、交互 |
| Phase 9 风险 | [20-Risk-Analysis](20-Risk-Analysis.md) | 技术/模型/医学/性能/维护风险 |
| Phase 10 任务 | [17-Development-Roadmap](17-Development-Roadmap.md) / [18-Task-Breakdown](18-Task-Breakdown.md) | Epic→Feature→Task→Subtask、DoD、验收标准 |
| 质量保障 | [19-Test-Plan](19-Test-Plan.md) | 单元/集成/性能测试计划 |
| 部署 | [21-Deployment](21-Deployment.md) | Docker Compose / Kubernetes |
| 部署手册（操作版） | [deployment-guide](deployment-guide.md) | 非技术人员逐步部署（T8.5） |
| 用户手册 | [user-manual](user-manual.md) | 医生/科研全流程操作（T8.5） |
| 安全审查 | [security-review](security-review.md) | T8.4 清单（越权/注入/上传/密钥/依赖） |
| 依赖审计 | [licenses-report](licenses-report.md) | pip-audit + pip-licenses 结论与豁免 |
| 性能压测 | [perf-report](perf-report.md) | T8.3 实测（10w×50 全链路 384s） |
| 演进 | [22-Future-Extensions](22-Future-Extensions.md) | FHIR/OMOP、MCP、Agent、插件市场 |
| 收尾 | [Appendix](Appendix.md) | Architecture Review Gate 结果、Implementation Readiness Checklist、术语表 |

## 核心设计决策（速览）

| 决策 | 结论 | 理由 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI | 与 ML 生态同语言，异步 IO 支撑上传/轮询 |
| 异步任务 | Celery + Redis | 多模型并行分析是长任务，必须异步 + 进度推送 |
| 数据库 | PostgreSQL 15 | JSONB 存灵活的分析配置与结果摘要，关系表存元数据 |
| 文件存储 | MinIO（S3 兼容） | 原始 CSV、中间产物、报告文件统一管理 |
| 前端 | React 18 + TypeScript + Vite + Ant Design + ECharts | 中文生态好、表格/表单组件成熟 |
| ML 库 | scikit-learn / lifelines / scikit-survival / pycox / xgboost / lightgbm / catboost / shap | 全部成熟开源，不重造轮子 |
| 预处理参考 | ehrapy（复用其 QC/缺失值/编码思路，按需二次开发） | 见 16 章调研 |
| 报告 | Jinja2 模板 → HTML / WeasyPrint(PDF) / python-docx(Word) / Markdown | 四种格式单一模板源 |
| 模型扩展 | 入口点（entry-points）模型注册表 + 插件协议 | 新增模型不改核心代码 |
| 部署 | Docker Compose（单机/科室）→ Kubernetes（院级/多租户） | 渐进式 |

## 对原始需求的两点主动修正（详见 Appendix 架构审查）

1. **Module 4「不要要求用户自己选择」调整为「自动推荐 + 用户可确认/覆盖」**：临床场景下完全自动识别任务类型有误判风险（例如同时存在生存时间与二分类结局），误判代价高。折中方案：平台自动推断并给出置信度与理由，用户一键确认或修改。
2. **报告默认只生成 HTML + PDF 两种**，Markdown/Word 作为 P2 可选项——四种格式同步维护成本高，先保证两种格式质量。

## 与 DVPlan.md 的映射

DVPlan.md 中的 Phase 1–10、Constraints、以及两条增强要求（Architecture Review Gate、Implementation Readiness Checklist）均已覆盖：Review Gate 结果与 Checklist 见 [Appendix](Appendix.md)。
