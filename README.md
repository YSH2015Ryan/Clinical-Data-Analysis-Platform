# Clinical Data Analysis Platform (CDAP)

临床数据分析平台：上传临床 CSV/Excel → 自动数据校验 → 可配置预处理 → 自动识别分析任务 → 多模型并行分析 → 模型比较与推荐 → 一键生成临床分析报告（PDF/HTML）。面向不会编程的医生与科研人员。

## 仓库结构

```
├── docs/        # 开发蓝图（24 份文档，编码的唯一契约依据，入口 docs/README.md）
├── backend/     # FastAPI + Celery（规划见 docs/02、docs/12）
├── frontend/    # React 18 + TS + Vite（规划见 docs/11）
├── deploy/      # docker-compose / k8s（见 docs/21）
└── CLAUDE.md    # AI Coding Agent 执行规范（强制）
```

## 当前状态

**M1–M4 全部完成**：蓝图执行完毕（docs/18 全部任务 DoD 达标）。性能实测见 [docs/perf-report.md](docs/perf-report.md)；安全审查见 [docs/security-review.md](docs/security-review.md)。

## 快速开始

```bash
cd deploy
cp .env.example .env   # 填入随机密钥
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python -m app.scripts.create_user \
    --email admin@example.com --password '<随机>' --role admin
```

逐步图文指引：[docs/deployment-guide.md](docs/deployment-guide.md)（面向非技术人员）；使用说明：[docs/user-manual.md](docs/user-manual.md)。

## 许可与合规

- 仅供科研用途，不构成临床诊断建议。
- 仓库禁止包含任何真实/未脱敏患者数据。
