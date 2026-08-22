# CDAP Tailscale 故障排查文档

## 问题：文件上传后出现 404 错误

### 症状
- 文件上传请求返回 202 Accepted
- 上传后尝试访问文件时出现 **404 page not found** 错误
- 浏览器尝试从 Tailscale 存储端点下载文件失败

### 根本原因

**Tailscale Funnel 10000 端口配置错误**，指向了错误的本地端口：

```bash
# ❌ 错误配置
https://codex-pc.tail409d12.ts.net:10000 (Funnel on)
|-- / proxy http://127.0.0.1:5173   # 错误！5173 不是 MinIO 端口

# ✅ 正确配置
https://codex-pc.tail409d12.ts.net:10000 (Funnel on)
|-- / proxy http://127.0.0.1:9000   # 正确！MinIO 在 9000 端口
```

### 为什么会出现这个问题

1. Tailscale Funnel 配置不会持久化保存在配置文件中
2. 系统重启或 Tailscale 服务重启后，Funnel 配置会丢失
3. 之前的临时配置（5173）被意外保留，导致端口映射错误
4. 即使 `.env` 和 `docker-compose.yml` 配置正确，如果 Funnel 配置错误，外网访问仍然失败

### 完整解决方案

#### 1. 配置 `.env` 文件

```bash
# deploy/.env
PG_PASSWORD=<your-password>
MINIO_ROOT_USER=cdap-admin
MINIO_ROOT_PASSWORD=<your-password>
JWT_SECRET=<your-secret>
LOG_LEVEL=INFO
MAX_UPLOAD_MB=200
PIP_INDEX_URL=https://pypi.org/simple

REDIS_PASSWORD=<your-password>
MINIO_APP_USER=cdap-storage
MINIO_APP_PASSWORD=<your-password>
ENVIRONMENT=prod

# Tailscale 配置（关键！）
TAILSCALE_HOSTNAME=codex-pc.tail409d12.ts.net
PUBLIC_DOMAIN=codex-pc.tail409d12.ts.net:8443
STORAGE_DOMAIN=codex-pc.tail409d12.ts.net:10000
```

#### 2. 使用正确的 compose 文件启动服务

```bash
cd deploy

# 停止所有服务
docker compose down

# 使用 Tailscale overlay 启动
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d

# 验证环境变量
docker exec cdap-api-1 printenv | grep S3_PUBLIC_ENDPOINT
# 应该输出: S3_PUBLIC_ENDPOINT=https://codex-pc.tail409d12.ts.net:10000
```

#### 3. 配置 Tailscale Funnel（每次系统重启后必须执行）

```bash
# 重置所有 Funnel 配置（清除错误配置）
tailscale funnel reset

# 配置 MinIO 存储端点（10000 -> 9000）
tailscale funnel --bg --https 10000 http://127.0.0.1:9000

# 配置前端应用端点（8443 -> 8080）
tailscale funnel --bg --https 8443 http://127.0.0.1:8080

# 验证配置
tailscale funnel status
```

**期望的输出：**
```
# Funnel on:
#     - https://codex-pc.tail409d12.ts.net:8443
#     - https://codex-pc.tail409d12.ts.net:10000

https://codex-pc.tail409d12.ts.net:10000 (Funnel on)
|-- / proxy http://127.0.0.1:9000

https://codex-pc.tail409d12.ts.net:8443 (Funnel on)
|-- / proxy http://127.0.0.1:8080
```

### 验证步骤

1. **检查 Docker 服务**
```bash
docker ps --filter "name=cdap" --format "table {{.Names}}\t{{.Status}}"
# 所有服务应该是 Up 且 healthy
```

2. **检查 MinIO 端口**
```bash
docker port cdap-minio-1
# 应该输出: 9000/tcp -> 127.0.0.1:9000
```

3. **检查前端端口**
```bash
docker port cdap-frontend-1
# 应该输出: 80/tcp -> 127.0.0.1:8080
```

4. **检查 Funnel 配置**
```bash
tailscale funnel status
# 确认 10000 -> 9000, 8443 -> 8080
```

5. **测试文件上传**
   - 访问 https://codex-pc.tail409d12.ts.net:8443/
   - 上传一个测试文件
   - 上传成功后不应该出现 404 错误
   - 文件预览和下载应该正常工作

### 自动化脚本

创建 `deploy/restart-with-funnel.sh`（Windows 用 .ps1）：

```powershell
# restart-with-funnel.ps1
# 完整重启 CDAP 并配置 Tailscale Funnel

Write-Host "停止服务..." -ForegroundColor Yellow
docker compose down

Write-Host "启动服务..." -ForegroundColor Yellow
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d

Write-Host "等待服务启动..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

Write-Host "配置 Tailscale Funnel..." -ForegroundColor Yellow
tailscale funnel reset
tailscale funnel --bg --https 10000 http://127.0.0.1:9000
tailscale funnel --bg --https 8443 http://127.0.0.1:8080

Write-Host "`n配置完成！" -ForegroundColor Green
Write-Host "前端: https://codex-pc.tail409d12.ts.net:8443/" -ForegroundColor Cyan
Write-Host "存储: https://codex-pc.tail409d12.ts.net:10000/" -ForegroundColor Cyan

Write-Host "`n验证配置..." -ForegroundColor Yellow
tailscale funnel status
docker ps --filter "name=cdap" --format "table {{.Names}}\t{{.Status}}"
```

### 常见错误模式

#### 错误 1：Funnel 指向错误端口
```bash
# 症状：文件上传后 404
# 原因：10000 端口没有指向 MinIO (9000)
# 解决：tailscale funnel reset && 重新配置
```

#### 错误 2：未使用 Tailscale overlay
```bash
# 症状：S3_PUBLIC_ENDPOINT=https://localhost
# 原因：只用了 docker-compose.yml，没用 docker-compose.tailscale.yml
# 解决：docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d
```

#### 错误 3：.env 配置错误
```bash
# 症状：即使用了 overlay，S3_PUBLIC_ENDPOINT 仍然是 localhost
# 原因：STORAGE_DOMAIN=localhost
# 解决：修改 .env 中的 STORAGE_DOMAIN 和 PUBLIC_DOMAIN
```

### 调试命令

```bash
# 查看实际环境变量
docker exec cdap-api-1 printenv | grep -E "S3_|STORAGE_|PUBLIC_"

# 查看 MinIO 中的文件
docker exec cdap-minio-1 mc ls local/cdap/

# 查看 API 日志
docker logs cdap-api-1 --tail 100

# 查看前端 Nginx 日志
docker logs cdap-frontend-1 --tail 100

# 查看 Worker 日志（文件处理）
docker logs cdap-worker-1 --tail 100

# 实时监控所有日志
docker compose logs -f api frontend worker
```

### 端口映射总结

| 服务 | 容器内部端口 | 主机端口 | Tailscale Funnel | 公网访问 |
|-----|------------|---------|-----------------|---------|
| Frontend | 80 | 127.0.0.1:8080 | 8443 | https://codex-pc.tail409d12.ts.net:8443 |
| MinIO | 9000 | 127.0.0.1:9000 | 10000 | https://codex-pc.tail409d12.ts.net:10000 |
| API | 8000 | (内部) | - | 通过 Frontend nginx 代理 |

### 重要提示

1. **Funnel 配置不持久**：系统重启后必须重新运行 `tailscale funnel` 命令
2. **必须使用两个 compose 文件**：`docker-compose.yml` + `docker-compose.tailscale.yml`
3. **端口映射必须正确**：10000 → 9000 (MinIO), 8443 → 8080 (Frontend)
4. **验证是关键**：每次修改后都要验证 `tailscale funnel status` 和环境变量

## 最后更新

- 日期: 2026-08-21
- 问题: ✅ 已彻底解决
- 根本原因: Tailscale Funnel 端口映射错误（10000 → 5173 而非 9000）
