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

**M0 准备阶段**：蓝图已完成并通过架构评审；API 契约已冻结（docs/14 §5, v1.0-frozen）。开发按 docs/17 路线图、docs/18 任务拆分执行。

## 快速开始

```bash
cd deploy && docker compose up -d   # M0 完成后可用
```

## 许可与合规

- 仅供科研用途，不构成临床诊断建议。
- 仓库禁止包含任何真实/未脱敏患者数据。
