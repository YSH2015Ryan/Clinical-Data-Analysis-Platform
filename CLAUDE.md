# CLAUDE.md — CDAP 开发执行规范

> 本文件是 AI Coding Agent 与本仓库协作的**强制约束**。蓝图即契约：完整开发计划见 `docs/`（24 份文档），与蓝图冲突时先提变更更新文档，再改代码，禁止静默偏离。

## 项目一句话

临床数据分析平台：上传 CSV/Excel → 自动校验 → 可配置预处理 → 自动识别任务类型（用户确认）→ 多模型并行分析（Celery chord）→ 模型比较推荐 → 临床报告（PDF/HTML）。复用成熟开源库，**不重新实现已有算法**。

## 技术栈（锁定）

Python 3.11 / FastAPI / Celery + Redis / PostgreSQL 15 + SQLAlchemy 2.0 + Alembic / MinIO(S3) / React 18 + TypeScript + Vite + AntD 5 + ECharts / scikit-learn + lifelines + scikit-survival + pycox + xgboost + lightgbm + catboost + SHAP / Jinja2 + WeasyPrint。详见 `docs/03-Technology-Stack.md`。

## 十条执行规范（源自 docs/Appendix.md C 节）

1. **蓝图即契约**：实现以 `docs/` 为准；冲突时先改文档再改代码。
2. **不重新实现已有成熟算法**：指标/模型/预处理一律调用技术栈清单中的库；新增依赖须在 PR 说明理由并通过许可证检查（GPL 敏感：scikit-survival 见 docs/16 §5）。
3. **分层纪律**：`backend/app/engines/*` 禁止 import fastapi / celery / sqlalchemy.orm.Session；`api/*` 不得直接操作 ORM（经 services）；CI import-linter 强制。
4. **契约同源**：API 改动必须先改 `docs/14-API-Specification.md`（已冻结 v1.0-frozen，变更流程见其 §5）与 Pydantic schema；前端类型只从 OpenAPI 生成物获取，禁止手写接口类型。
5. **测试先行**：引擎模块先写失败测试（对应 docs/19 条目）再实现；每个 PR 附对应单测；覆盖率门槛 engines ≥85%、整体后端 ≥80%。
6. **幂等与隔离**：所有 worker 任务幂等（DB 唯一约束兜底）；单模型失败不得影响其他模型；随机种子统一 seed=42。
7. **安全红线**：禁止 eval/exec 用户输入（derive 表达式走白名单求值）；SQL 全部参数化；密钥不进仓库；上传走扩展名白名单 + magic bytes 嗅探。
8. **结果真实**：报告与推荐理由只引用真实计算指标，禁止生成未计算的数值或医学断言；报告必须含免责声明。
9. **提交规范**：Conventional Commits；PR 关联 docs/18 章 Task 编号（如 `T5.3`）。
10. **完成定义**：以各 Task 的 DoD + 验收标准为准（docs/18），而非「代码能跑」。

## 关键文档速查

| 事项 | 文档 |
|---|---|
| API 契约（已冻结） | docs/14-API-Specification.md |
| 数据库 DDL | docs/13-Database-Design.md |
| 任务拆分与 DoD | docs/18-Task-Breakdown.md |
| 测试要求 | docs/19-Test-Plan.md |
| 预处理 DSL | docs/06-Preprocessing-Pipeline.md |
| 状态机/编排 | docs/08-Analysis-Workflow.md |

## 环境注意

- 本机 Python 3.9 仅用于工具脚本；后端运行/测试一律在容器内（python:3.11 镜像）。
- 禁止将任何真实患者数据、未脱敏数据提交进仓库；测试数据只能用 `tests/fixtures/` 下的合成或已脱敏数据。
