# Tailscale Funnel 配置记录

## 问题诊断

之前的 Funnel 配置指向了错误的端口（5173），而实际 CDAP 服务运行在不同端口上。

## 当前配置

### 公网访问端点（Funnel 已启用）

1. **主应用前端**
   - 公网 URL: https://codex-pc.tail409d12.ts.net:8443/
   - 代理目标: http://127.0.0.1:8080 (cdap-frontend-1 容器)
   - 状态: ✅ 可访问 (HTTP 200)

2. **MinIO 对象存储**
   - 公网 URL: https://codex-pc.tail409d12.ts.net:10000/
   - 代理目标: http://127.0.0.1:9000 (cdap-minio-1 容器)
   - 状态: ✅ 运行中 (S3 API 端点)

### Tailscale 信息

- 设备名: codex-pc
- Tailnet: tail409d12.ts.net
- 本机 IP: 100.82.194.104

## 执行的修复步骤

```powershell
# 1. 重置旧配置
tailscale serve reset
tailscale funnel off

# 2. 配置前端公网访问
tailscale funnel --bg --https 8443 http://127.0.0.1:8080

# 3. 配置 MinIO 公网访问
tailscale funnel --bg --https 10000 http://127.0.0.1:9000
```

## 验证命令

```powershell
# 查看当前 Funnel 状态
tailscale funnel status

# 测试前端访问
Invoke-WebRequest -Uri "https://codex-pc.tail409d12.ts.net:8443/" -UseBasicParsing

# 查看 Docker 服务状态
docker ps --filter "name=cdap"
```

## 服务端口映射

| 服务 | 容器端口 | 主机端口 | Tailscale HTTPS 端口 |
|-----|---------|---------|---------------------|
| Frontend | 80 | 127.0.0.1:8080 | 8443 |
| MinIO API | 9000 | 127.0.0.1:9000 | 10000 |
| API Backend | 8000 | (内部网络) | - |
| PostgreSQL | 5432 | (内部网络) | - |
| Redis | 6379 | (内部网络) | - |

## 注意事项

1. **安全性**: Funnel 将服务暴露到公网，确保：
   - 应用层有完善的身份验证
   - MinIO 使用了强密码
   - JWT_SECRET 保持安全

2. **配置持久化**: 当前 Funnel 配置在后台运行，系统重启后需要重新执行 funnel 命令

3. **证书**: Tailscale 自动提供有效的 HTTPS 证书，无需额外配置

4. **与 docker-compose.tailscale.yml 的关系**:
   - docker-compose 配置定义了服务的本地端口绑定（127.0.0.1）
   - Tailscale Funnel 负责将这些本地端口安全地暴露到公网
   - S3_PUBLIC_ENDPOINT 设置为 `https://codex-pc.tail409d12.ts.net:10000`

## 故障排查

如果再次无法访问：

1. 检查 Tailscale 状态: `tailscale status`
2. 检查 Funnel 配置: `tailscale funnel status`
3. 检查 Docker 容器: `docker ps --filter "name=cdap"`
4. 检查本地端口监听: `netstat -an | findstr "8080 9000"`
5. 重新应用 Funnel 配置（见上述命令）

## 文件上传 404 错误修复

### 问题原因

初始配置中 `.env` 文件的 `STORAGE_DOMAIN=localhost`，导致容器运行时 `S3_PUBLIC_ENDPOINT` 被设置为 `https://localhost`，而不是 Tailscale 的公网端点。

当用户上传文件后，前端尝试从 `https://localhost` 下载预览或访问文件时会出现 **404 page not found** 错误。

### 修复步骤

1. 更新 `.env` 文件中的域名配置：
```bash
TAILSCALE_HOSTNAME=codex-pc.tail409d12.ts.net
PUBLIC_DOMAIN=codex-pc.tail409d12.ts.net:8443
STORAGE_DOMAIN=codex-pc.tail409d12.ts.net:10000
```

2. 使用 Tailscale overlay 配置重启服务：
```bash
cd deploy
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d api worker beat
```

3. 验证配置：
```bash
docker exec cdap-api-1 printenv | grep S3_PUBLIC_ENDPOINT
# 应该输出: S3_PUBLIC_ENDPOINT=https://codex-pc.tail409d12.ts.net:10000
```

### 启动服务的正确命令

**重要**：必须同时指定两个 compose 文件：

```bash
cd deploy
# 启动所有服务
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d

# 重启特定服务
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml restart api worker beat
```

## 最后更新

- 日期: 2026-08-21
- 状态: ✅ 已修复并验证（包括文件上传 404 问题）
- 访问地址: https://codex-pc.tail409d12.ts.net:8443/
- 存储端点: https://codex-pc.tail409d12.ts.net:10000/
