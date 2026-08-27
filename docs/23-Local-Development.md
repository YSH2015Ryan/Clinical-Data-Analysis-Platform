# 23. 本地开发与调试指南

> 面向本机(Windows)开发者的日常调试流程。生产部署见 docs/21;本指南的 compose 与生产完全独立。
> 约束回顾(CLAUDE.md):本机 Python 3.9 仅用于工具脚本;后端运行/测试一律在容器内(python:3.11 镜像)。

## 1. 架构一览

| 组件 | 运行在哪 | 调试方式 |
|---|---|---|
| 前端 Vite | **宿主机** `npm run dev`(端口 5173) | 浏览器 DevTools;`/api` 已代理到 `localhost:8000`(vite.config.ts) |
| API(FastAPI) | 容器,源码挂载 + uvicorn `--reload` | 改代码自动重载;VS Code attach 5678 断点 |
| Worker(Celery) | 容器,`--pool=solo` + watchfiles 自动重启 | 改代码自动重启;VS Code attach 5679 断点 |
| Beat / Postgres / Redis / MinIO | 容器 | 日志排查 |
| LLM(Ollama) | 宿主机或服务器(T6.6 落地后生效) | `.env.dev` 的 `OLLAMA_BASE_URL` 切换 |

## 2. 首次启动

```bash
# 1) 启动后端全家桶(首次 --build,装依赖较慢;之后改代码无需重建)
cd deploy
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d --build

# 2) 启动前端(宿主机;node_modules 已存在则跳过 install)
cd ../frontend
npm install
npm run dev
```

访问:http://localhost:5173(前端)/ http://localhost:8000/docs(API)/ http://localhost:9001(MinIO 控制台,devroot/devroot123)。

**何时需要重新 `--build`**：只有改了 `backend/pyproject.toml` 依赖或 Dockerfile 时才需要；日常改 `app/` 下代码靠热重载，秒级生效。

## 3. 断点调试(VS Code)

1. 确认 dev compose 在跑(debugpy 常驻监听，不 attach 也不影响运行)。
2. 在 `backend/app/**` 打断点。
3. F5 选择 **"Attach: API + Worker"**(或单独 attach)；断点不命中时检查：
   - 是否 attach 对了进程：HTTP 请求 → 5678(API)；分析/报告任务 → 5679(Worker)。
   - `pathMappings` 已配好(`/app/app` ↔ `backend/app`)，不要打断点在 `tests/` 以外的未挂载路径。

## 4. 跑测试(全部在容器内)

```bash
cd deploy
# 全量
docker compose -f docker-compose.dev.yml exec api pytest /app/tests -x -q
# 单文件 / 单用例
docker compose -f docker-compose.dev.yml exec api pytest /app/tests/plugins/test_gam.py -q
# 覆盖率(门槛:engines ≥85%,整体 ≥80% —— CLAUDE.md 规范5)
docker compose -f docker-compose.dev.yml exec api pytest /app/tests --cov=app --cov-report=term-missing -q
# lint / 类型
docker compose -f docker-compose.dev.yml exec api ruff check app tests
docker compose -f docker-compose.dev.yml exec api mypy app
```

## 5. 常用运维动作

```bash
# 看日志(排查 worker 失败首选)
docker compose -f docker-compose.dev.yml logs -f worker
docker compose -f docker-compose.dev.yml logs -f api

# 数据库变更后重新迁移
docker compose -f docker-compose.dev.yml run --rm migrate

# 进容器排查 / 手动跑脚本
docker compose -f docker-compose.dev.yml exec api bash
docker compose -f docker-compose.dev.yml exec worker python -c "from app.celery_app import *"

# 连数据库(DBeaver/psql):localhost:5433,库 cdap,用户 cdap,密码见 .env.dev
# 连 Redis:localhost:6380,密码见 .env.dev

# 清空重来(删数据卷,慎用)
docker compose -f docker-compose.dev.yml down -v
```

## 6. 端到端调试一条分析链路

1. 前端 5173 上传 `backend/tests/fixtures/` 下的合成数据(**禁止真实患者数据**,CLAUDE.md 红线)。
2. 校验环节：attach API 断 `engines/validation.py`;前端看 quality-report 响应。
3. 发起分析：attach Worker 断 `workers/analysis_tasks.py` 的 `run_model`;solo 池下任务逐个执行，断点稳定。
4. 报告：断 `workers/report_tasks.py` / `engines/reporting/context.py`;HTML 报告可从 MinIO 控制台直接下载核对。
5. LLM 相关(T6.6 之后）:`.env.dev` 切 `OLLAMA_BASE_URL`;调不通时先看 `docker compose ... logs api | grep -i llm`。

## 7. Windows 特有坑

- **热重载不生效**:compose 里已设 `WATCHFILES_FORCE_POLLING=true`(Docker Desktop 挂载不传 inotify 事件)；若仍不灵，确认改的是 `backend/app/`(已挂载）而非其他目录。
- **行尾符**：仓库统一 LF;git 配置 `core.autocrlf=true` 即可，挂载进容器后不影响。
- **性能**:Docker Desktop 建议用 WSL2 后端；仓库放在 Windows 盘挂载 I/O 较慢属正常，大型数据训练在容器内跑、数据走 MinIO 卷，不受影响。
- **端口冲突**:5433/6380/5678/5679/9000/9001/8000/5173 被占时改 compose 左侧宿主端口。

## 8. 与服务器端同事的边界

- 本文档与 `docker-compose.dev.yml`、`.env.dev` 只服务本机调试；服务器部署仍用 `docker-compose.yml` + `deploy/.env`(不入库)。
- `.env.dev` 内是公开的开发占位密钥，可提交；**任何真实密钥禁止写入该文件**。
- 改了 `pyproject.toml` 依赖后记得告知对方：服务器镜像需重新构建。
