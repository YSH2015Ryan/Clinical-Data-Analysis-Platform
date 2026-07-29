# 21. 部署方案（Deployment）

## 1. 部署形态

| 形态 | 场景 | 组件 |
|---|---|---|
| **单机 Docker Compose**（v1 默认） | 科室/课题组，单服务器 | 7 容器（见下） |
| **Kubernetes**（v1.x 可选） | 院级/多团队 | Deployment + HPA + 外部 PG/S3 |

## 2. Docker Compose（deploy/docker-compose.yml 摘要）

```yaml
services:
  frontend:
    build: ../frontend
    ports: ["80:80"]
    depends_on: [api]
  api:
    build: ../backend
    command: uvicorn app.main:app --host 0.0.0.0 --workers 2
    environment:
      DATABASE_URL: postgresql://cdap:${PG_PASSWORD}@postgres:5432/cdap
      REDIS_URL: redis://redis:6379/0
      S3_ENDPOINT: http://minio:9000
      JWT_SECRET: ${JWT_SECRET}
    depends_on: [postgres, redis, minio]
  worker:
    build: ../backend
    command: celery -A app.workers.celery_app worker -Q default,model,report --concurrency=4
    environment: *same-as-api
    deploy: {resources: {limits: {memory: 6G}}}
    depends_on: [postgres, redis, minio]
  beat:
    build: ../backend
    command: celery -A app.workers.celery_app beat
  postgres:
    image: postgres:15
    volumes: [pgdata:/var/lib/postgresql/data]
  redis:
    image: redis:7
    volumes: [redisdata:/data]
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    volumes: [miniodata:/data]
volumes: {pgdata: {}, redisdata: {}, miniodata: {}}
```

- worker 镜像内置：CPU torch、Noto Sans CJK、pango（WeasyPrint）。
- 横向扩展：`docker compose up --scale worker=4`。
- 首启初始化：Alembic upgrade → 创建 admin（环境变量种子）→ 同步 model_plugins 表。

## 3. 环境变量清单

| 变量 | 默认 | 说明 |
|---|---|---|
| PG_PASSWORD / JWT_SECRET / MINIO_ROOT_PASSWORD | 无（必填） | 部署时生成，禁止提交仓库 |
| MAX_UPLOAD_MB | 200 | 上传上限 |
| MODEL_TIMEOUT_S | 900 | 单模型超时 |
| WORKER_CONCURRENCY | CPU 核数 | celery 并发 |
| REPORT_RETENTION_DAYS | 0（永久） | 报告保留期，0=不清理 |
| LOG_LEVEL | INFO | — |

## 4. Kubernetes（要点）

```mermaid
flowchart TB
    IN[Ingress TLS] --> FE[frontend Deploy x2]
    IN --> API[api Deploy x2<br/>HPA: CPU>70%]
    API --> PG[(外部 PG / CloudNativePG)]
    API --> RD[(Redis)]
    API --> S3[(MinIO Operator / 外部 S3)]
    W[worker Deploy<br/>HPA: 队列深度 KEDA] --> PG & RD & S3
    B[beat Deploy x1] --> RD
```

- KEDA ScaledObject 按 Redis 队列长度扩缩 worker。
- Secret 管理：K8s Secret + 可选 External Secrets。
- 存储：PG/MinIO 用 PVC（SSD）；备份：PG 每日 pg_dump + S3 版本化。

## 5. 备份与升级

| 项 | 策略 |
|---|---|
| 备份 | 每日 `pg_dump` → S3；MinIO 开启版本控制；保留 30 天 |
| 升级 | 镜像 tag 不可变（git sha）；升级 = 拉新镜像 + `alembic upgrade head`；回滚 = 旧镜像 + 预先 downgrade 脚本 |
| 健康 | `/healthz`（liveness）、`/readyz`（readiness）；compose `restart: unless-stopped` |

## 6. 安全基线

- TLS：Nginx/Ingress 终结，证书 cert-manager 或手动。
- 容器非 root 运行；只读根文件系统（除 tmp）。
- 网络：compose 内网；K8s NetworkPolicy（仅 ingress→api/frontend，api/worker→pg/redis/minio）。
- 密码/密钥仅经环境变量注入；日志脱敏（不记录文件内容、不记录 token）。
