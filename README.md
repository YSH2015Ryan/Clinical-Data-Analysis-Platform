# Clinical Data Analysis Platform (CDAP)

临床数据分析平台：上传临床 CSV/Excel → 自动数据校验 → 可配置预处理 → 自动识别分析任务 → 多模型并行分析 → 模型比较与推荐 → 一键生成临床分析报告（PDF / HTML / Word / Markdown）。面向不会编程的医生与科研人员。

## 功能特性

- **数据接入**：CSV / TSV / TXT / Excel（.xlsx/.xls）上传，≤200MB；扩展名白名单 + magic bytes 嗅探
- **自动校验**：阻塞/警告分级问题清单、列画像（缺失率/异常值/取值范围）、一键修复（生成新版本，原始文件不动）
- **预处理 DSL**：缩放/编码/分箱/缺失值填补/衍生列（白名单沙箱求值），版本化管理可回溯
- **任务识别**：自动推荐分类 / 回归 / 生存分析（含置信度与理由），用户确认或改选
- **多模型并行**：Celery chord 编排，内置 14 个模型插件（logreg/rf/svm/xgboost/lightgbm/catboost + 回归 + Cox/RSF/GBS 生存分析），单模型失败互不影响
- **模型比较**：主指标 60% + 稳定性 20% + 次要指标 20% 加权排名，推荐理由只引用真实计算指标
- **可解释性**：GBDT 走 SHAP 快速路径，sklearn 森林用内置特征重要性（docs/07 §6）
- **报告**：单一 Jinja2 模板源输出 PDF（WeasyPrint，嵌入 Noto CJK）/ HTML / Word / Markdown，含免责声明
- **权限与审计**：JWT + RBAC（admin/researcher/viewer）+ 项目级数据隔离 + 关键操作审计日志

## 仓库结构

```
├── docs/        # 开发蓝图（24 份文档 + 审查/压测/手册，编码的契约依据，入口 docs/README.md）
├── backend/     # FastAPI + Celery + PostgreSQL + MinIO（设计见 docs/12）
├── frontend/    # React 18 + TypeScript + Vite + AntD 5 + ECharts（设计见 docs/11）
├── deploy/      # docker-compose / k8s（方案见 docs/21，操作手册 docs/deployment-guide.md）
└── CLAUDE.md    # AI Coding Agent 执行规范（强制）
```

## 项目状态

**✅ 已完成（M0–M4 全部里程碑，docs/18 全部任务 DoD 达标）**

- 测试：520+ 用例；总覆盖率 88%（engines ≥85%）；CI 五门禁（ruff / mypy / import-linter / pytest / pip-audit+licenses / docker build）
- 性能实测（10 万行 × 50 列 × 6 模型，顺序执行上界）：全链路 384s ≤ 600s 目标 — [docs/perf-report.md](docs/perf-report.md)
- 安全审查（越权/注入/上传/密钥/依赖）全项 PASS — [docs/security-review.md](docs/security-review.md)

## 快速开始

```bash
cd deploy
cp .env.example .env   # 填入随机密钥
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python -m app.scripts.create_user \
    --email admin@example.com --password '<随机>' --role admin
```

浏览器访问 `http://localhost:8080`。

- 部署指引（面向非技术人员）：[docs/deployment-guide.md](docs/deployment-guide.md)
- 使用手册（面向医生/科研）：[docs/user-manual.md](docs/user-manual.md)

## 许可与合规

- 仅供科研用途，不构成临床诊断建议（报告内含同样免责声明）。
- 仓库禁止包含任何真实/未脱敏患者数据；测试数据均为合成数据。
- 依赖许可证审计见 [docs/licenses-report.md](docs/licenses-report.md)（scikit-survival 为 GPL-3.0，院内科研自用场景登记为已知风险 R4）。
