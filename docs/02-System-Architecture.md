# 02. 系统架构（System Architecture）

## 1. 总体架构

```mermaid
flowchart TB
    subgraph Client["客户端"]
        UI["React 18 + TypeScript SPA<br/>(Ant Design + ECharts/Plotly)"]
    end

    subgraph Edge["接入层"]
        NGINX["Nginx<br/>静态资源 / 反向代理 / TLS"]
    end

    subgraph Backend["后端服务 (FastAPI)"]
        API["REST API 层<br/>(routers: auth/projects/datasets/analysis/reports)"]
        SVC["业务服务层<br/>ProjectService / DatasetService<br/>AnalysisOrchestrator / ReportService"]
        VAL["数据校验引擎"]
        PRE["预处理流水线引擎"]
        TASKDET["任务类型自动识别器"]
        MREG["模型注册表<br/>(Model Registry + 插件)"]
        RPT["报告生成引擎<br/>(Jinja2 → HTML/PDF)"]
        AUTH["鉴权与审计<br/>(JWT / RBAC / AuditLog)"]
    end

    subgraph Workers["异步计算层 (Celery)"]
        WQ["任务队列 (Redis Broker)"]
        CW["Celery Workers<br/>validation / preprocess / model-run / report"]
        BEAT["Celery Beat<br/>清理/心跳"]
    end

    subgraph Data["数据层"]
        PG[("PostgreSQL 15<br/>元数据 + JSONB 结果摘要")]
        REDIS[("Redis<br/>Broker + 缓存 + 进度pub/sub")]
        MINIO[("MinIO (S3)<br/>原始文件/中间产物/报告")]
    end

    subgraph MLLib["ML 运行时 (Worker 内)"]
        SK["scikit-learn"]
        LF["lifelines"]
        SKS["scikit-survival"]
        PYCOX["pycox/DeepSurv (PyTorch)"]
        GBM["XGBoost / LightGBM / CatBoost"]
        SHAP["SHAP"]
        EHP["ehrapy (QC/预处理参考)"]
    end

    UI --> NGINX --> API
    API --> SVC
    SVC --> VAL & PRE & TASKDET & MREG & RPT & AUTH
    SVC -- "提交异步任务" --> WQ
    WQ --> CW
    CW --> MLLib
    SVC --> PG
    CW --> PG
    SVC --> REDIS
    CW --> MINIO
    SVC --> MINIO
    UI -. "WebSocket/SSE 进度" .-> API
```

## 2. 架构分层职责

| 层 | 组件 | 职责 | 不做的事 |
|---|---|---|---|
| 客户端 | React SPA | 上传、配置向导、进度展示、结果可视化、报告预览下载 | 任何计算 |
| 接入层 | Nginx | TLS、静态资源、反代、请求大小限制 | 业务逻辑 |
| API 层 | FastAPI routers | 请求校验（Pydantic）、鉴权、DTO 转换 | 计算、SQL 细节 |
| 服务层 | Services | 业务编排、事务、任务提交、结果聚合 | HTTP 细节 |
| 引擎层 | Validation/Preprocess/Registry/Report | 可独立测试的领域引擎，纯 Python | 依赖 FastAPI |
| 计算层 | Celery Workers | 长任务执行：校验、预处理、模型训练评估、报告渲染 | HTTP |
| 数据层 | PG/Redis/MinIO | 持久化、消息、缓存、对象存储 | — |

> **关键原则**：引擎层（Validation/Preprocess/Model/Report）不依赖 Web 框架，可被 API、CLI、未来 MCP Server 三种入口复用。

## 3. 模块架构图

```mermaid
flowchart LR
    subgraph Core["平台核心"]
        direction TB
        M1["模块1 数据导入<br/>ingest"]
        M2["模块2 数据校验<br/>validation"]
        M3["模块3 预处理<br/>preprocessing"]
        M4["模块4 任务识别<br/>task-detection"]
        M5["模块5 多模型分析<br/>modeling"]
        M6["模块6 模型比较<br/>comparison"]
        M7["模块7 报告<br/>reporting"]
        M1 --> M2 --> M3 --> M4 --> M5 --> M6 --> M7
    end

    subgraph Cross["横切能力"]
        AUTHX["认证/权限"]
        AUDIT["审计日志"]
        FS["文件存储抽象<br/>(S3/本地)"]
        CFG["配置中心"]
        PLUG["插件机制<br/>(模型/格式/模板)"]
        NOTIFY["进度通知<br/>(SSE/WebSocket)"]
    end

    Cross -.-> Core
```

## 4. 数据流图（DFD）

### Level 0

```mermaid
flowchart LR
    U([临床研究员]) -- "CSV/Excel + 配置" --> P(("CDAP 临床数据分析平台"))
    P -- "数据质量报告" --> U
    P -- "模型比较结果" --> U
    P -- "临床分析报告 PDF/HTML" --> U
    ADMIN([平台管理员]) -- "用户/插件管理" --> P
```

### Level 1

```mermaid
flowchart TB
    U([用户])
    P1(("1.0<br/>数据导入"))
    P2(("2.0<br/>数据校验"))
    P3(("3.0<br/>预处理"))
    P4(("4.0<br/>任务识别"))
    P5(("5.0<br/>多模型分析"))
    P6(("6.0<br/>模型比较"))
    P7(("7.0<br/>报告生成"))

    D1[("D1 数据集存储<br/>(MinIO+PG)")]
    D2[("D2 质量报告")]
    D3[("D3 处理后特征集")]
    D4[("D4 分析运行记录")]
    D5[("D5 模型结果/指标")]
    D6[("D6 报告文件")]

    U -- "上传文件" --> P1
    P1 -- "原始文件+元数据" --> D1
    P1 --> P2
    D1 --> P2
    P2 -- "质量报告" --> D2
    P2 -- "校验通过数据" --> P3
    P3 -- "特征矩阵+流水线快照" --> D3
    P3 --> P4
    P4 -- "任务类型+置信度" --> P5
    D3 --> P5
    P5 -- "各模型结果" --> D4
    P5 --> D5
    D5 --> P6
    P6 -- "排名+推荐" --> P7
    D4 --> P7
    P7 -- "报告文件" --> D6
    P7 -- "报告下载" --> U
    D2 -- "质量问题展示" --> U
```

## 5. 关键时序图

### 5.1 上传与校验

```mermaid
sequenceDiagram
    actor U as 用户
    participant FE as React 前端
    participant API as FastAPI
    participant DB as PostgreSQL
    participant S3 as MinIO
    participant Q as Celery/Redis
    participant W as Validation Worker

    U->>FE: 拖拽上传 CSV
    FE->>API: POST /datasets (multipart, 分片可选)
    API->>S3: 存储原始文件
    API->>DB: 创建 dataset 记录(status=UPLOADED)
    API->>Q: 提交 validate 任务
    API-->>FE: 202 {dataset_id, task_id}
    Q->>W: 执行校验
    W->>S3: 读取文件(编码/分隔符嗅探)
    W->>W: 运行校验规则引擎
    W->>DB: 写 quality_report (JSONB), status=VALIDATED/FAILED
    W->>Q: 发布进度事件
    FE->>API: GET /tasks/{id} (轮询) 或 SSE 订阅
    API-->>FE: 进度/完成 + quality_report
    FE->>U: 展示质量报告(阻塞项/警告+修正建议)
```

### 5.2 分析与报告

```mermaid
sequenceDiagram
    actor U as 用户
    participant FE as React 前端
    participant API as FastAPI
    participant ORCH as AnalysisOrchestrator
    participant Q as Celery Canvas
    participant MW as Model Workers
    participant DB as PostgreSQL
    participant S3 as MinIO

    U->>FE: 确认预处理配置/任务类型/模型集
    FE->>API: POST /analysis-runs
    API->>ORCH: 创建运行(快照所有参数)
    ORCH->>DB: run(status=PENDING) + 参数快照
    ORCH->>Q: chain( preprocess | chord( model_tasks[] , compare_cb ) )
    Q->>MW: 预处理(单任务)
    MW->>S3: 保存特征矩阵 parquet
    Q->>MW: chord: 并行执行 N 个模型任务
    par 并行模型
        MW->>MW: train/eval/CV
        MW->>DB: model_result(指标JSONB)
        MW->>S3: 图表/模型产物
    end
    Q->>MW: callback: 比较与排序
    MW->>DB: comparison(排名+推荐理由)
    ORCH->>DB: run(status=COMPLETED)
    FE->>API: 轮询/SSE 获取进度
    U->>FE: 点击「生成报告」
    FE->>API: POST /reports {run_id, format}
    API->>Q: 提交 report 任务
    Q->>MW: Jinja2 渲染 → WeasyPrint PDF
    MW->>S3: 存储报告文件
    FE->>API: GET /reports/{id}/download
```

## 6. 部署拓扑（逻辑）

```mermaid
flowchart TB
    subgraph DockerHost["单机 Docker Compose (v1 默认)"]
        C1[frontend (nginx+静态)]
        C2[api (fastapi, uvicorn x2)]
        C3[worker (celery, concurrency=CPU)]
        C4[beat]
        C5[(postgres)]
        C6[(redis)]
        C7[(minio)]
    end
    C1 --> C2
    C2 --> C5 & C6 & C7
    C3 --> C5 & C6 & C7
```

K8s 拓扑见 [21-Deployment](21-Deployment.md)。

## 7. 目录结构（后端 monorepo）

```
cdap/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口
│   │   ├── core/                    # 配置/安全/日志/异常
│   │   ├── api/v1/                  # routers: auth,projects,datasets,analysis,reports,plugins
│   │   ├── services/                # 业务服务层
│   │   ├── engines/                 # 领域引擎（框架无关，纯 Python）
│   │   │   ├── validation/          # 规则引擎 + 质量画像
│   │   │   ├── preprocessing/       # Pipeline DSL + 步骤实现
│   │   │   ├── task_detection/      # 列语义识别 + 任务推荐
│   │   │   ├── modeling/            # 模型适配器 + 注册表
│   │   │   ├── comparison/          # 指标汇总 + 排序推荐
│   │   │   └── reporting/           # 模板渲染 + 导出器
│   │   ├── models/                  # SQLAlchemy ORM
│   │   ├── schemas/                 # Pydantic DTO
│   │   ├── workers/                 # Celery 任务定义
│   │   ├── plugins/                 # 内置模型插件
│   │   └── tests/
│   ├── alembic/                     # 迁移
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/                   # Login/Projects/Dataset/Wizard/Results/Reports/Admin
│   │   ├── components/              # UploadZone/QualityReport/ModelTable/Charts
│   │   ├── api/                     # OpenAPI 生成客户端
│   │   └── stores/                  # Zustand
│   └── Dockerfile
├── deploy/
│   ├── docker-compose.yml
│   └── k8s/
└── docs/                            # 本目录
```

## 8. 横切设计要点

- **日志**：structlog JSON 日志，request_id/run_id 贯穿 API→Worker。
- **异常**：统一 `AppError(code, message, details)` → RFC7807 风格错误响应（错误码表见 14 章）。
- **权限**：JWT + 角色（admin/researcher/viewer），项目级隔离：`project.owner_id` 强制过滤。
- **缓存**：Redis 缓存模型注册表、任务进度；结果不缓存（每次运行独立快照）。
- **进度通知**：v1 用轮询（简单可靠）+ SSE 作为增强；WebSocket 非必需。
