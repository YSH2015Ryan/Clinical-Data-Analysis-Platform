# 03. 技术栈（Technology Stack）

## 1. 选型总表

| 层 | 技术 | 版本基线 | 选型理由 | 备选/未选理由 |
|---|---|---|---|---|
| 语言 | Python | 3.11 | ML 生态母语；性能足够 | 3.12 部分科学库兼容性待验证 |
| Web 框架 | FastAPI | 0.110+ | 异步、Pydantic 校验、自动 OpenAPI | Django 太重；Flask 无异步 |
| ASGI | Uvicorn | 0.29+ | 标准选择 | — |
| 任务队列 | Celery + Redis | 5.4+ | 成熟、支持 chain/chord 编排、重试 | Dramatiq 生态较小 |
| 数据库 | PostgreSQL | 15 | JSONB 支撑灵活结果存储、CTE/窗口函数强 | MySQL JSON 能力弱 |
| ORM/迁移 | SQLAlchemy 2.0 + Alembic | 2.0+ | 标准组合 | — |
| 对象存储 | MinIO | latest | S3 兼容、本地可跑、院内部署友好 | 直接文件系统不利于扩展 |
| 缓存/消息 | Redis | 7 | 一身三任：broker/缓存/进度 | RabbitMQ 多一组件 |
| 前端 | React 18 + TypeScript + Vite | — | 生态最大、TS 类型安全 | Vue 亦可，团队熟悉度优先 React |
| UI 组件 | Ant Design 5 | — | 中文文档、表格/表单/上传组件齐全 | MUI 中文生态弱 |
| 图表 | ECharts(前端) + Plotly(后端报告图) | — | ECharts 交互强；Plotly 可静态导出进报告 | — |
| 数据处理 | pandas / numpy / pyarrow | — | 标准 | Polars 生态待成熟 |
| 机器学习 | scikit-learn | 1.4+ | 基线模型/预处理/指标 | — |
| 生存分析 | lifelines + scikit-survival | — | KM/CoxPH 事实标准；RSF/GBS | 互补不互斥 |
| 深度生存 | pycox (DeepSurv, PyTorch) | — | 最成熟的 DeepSurv 实现 | 自实现违反约束 |
| 梯度提升 | XGBoost / LightGBM / CatBoost | — | 表格数据三剑客 | — |
| 可解释性 | SHAP | 0.45+ | 事实标准 | — |
| 临床预处理参考 | ehrapy | 最新稳定 | 复用 QC/缺失值/编码思想，按需二开 | 见 16 章 |
| 报告 | Jinja2 + WeasyPrint + python-docx + Markdown | — | 单模板源多格式 | LaTeX 部署重 |
| 校验 | Pydantic v2 + Pandera | — | API 校验 + DataFrame 校验 | great_expectations 偏重，P2 可评估 |
| 测试 | pytest / pytest-asyncio / httpx / coverage / locust | — | 标准 | — |
| 容器 | Docker + Docker Compose；K8s（后期） | — | 院内部署主流 | — |
| 代码质量 | ruff + mypy + pre-commit | — | 快、一体化 | — |
| CI | GitHub Actions | — | 标准 | — |

## 2. 版本锁定策略

- `pyproject.toml` 使用兼容范围（`~=`)，`uv.lock`/`poetry.lock` 锁定精确版本，CI 与镜像构建使用 lock 文件。
- 科学计算栈（numpy/pandas/scikit-learn/scipy）作为**升级敏感组**，升级需跑全量回归测试 + 金标准数据集结果比对（见 19 章）。

## 3. 关键依赖的风险与缓解

| 依赖 | 风险 | 缓解 |
|---|---|---|
| pycox/PyTorch | 体积大、GPU 非必需；安装慢 | CPU 版 torch；镜像分层缓存；DeepSurv 设为可选模型（默认开启但可禁用） |
| ehrapy | 依赖 anndata 生态较重 | 仅复用其 QC/预处理思路与部分函数，**不作为运行时硬依赖**，按需引入 |
| WeasyPrint | 系统依赖（pango/cairo）在 Windows 难装 | 运行于 Linux 容器内；前端预览用 HTML 不受影响 |
| LightGBM/CatBoost | 版本间结果差异 | lock 版本 + 金标准回归比对 |
| Celery | chord 在部分结果后端有限制 | 使用 Redis 结果后端，chord 场景在 19 章集成测试覆盖 |

## 4. 前后端协作

- OpenAPI Schema 由 FastAPI 自动生成 → 前端用 `openapi-typescript` 生成类型与客户端，**禁止手写接口类型**。
- 开发代理：Vite dev server proxy → `localhost:8000`。
