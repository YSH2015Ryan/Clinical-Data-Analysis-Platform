# 部署操作手册（T8.5；面向非技术人员）

> 目标：按本手册逐步执行，即可在一台服务器上把平台跑起来。全程复制粘贴命令即可，无需编程知识。
> 技术细节（架构、K8s 形态）见 [21-Deployment](21-Deployment.md)；本手册是「照做就行」的操作版。

## 0. 你需要准备什么

| 项 | 要求 |
|---|---|
| 服务器 | 1 台 Linux 服务器（院内物理机/虚拟机/云主机均可），建议 **4 核 CPU / 16GB 内存 / 100GB 磁盘** 以上（最低 4C8G，仅适合小数据量试用） |
| 操作系统 | Ubuntu 22.04 / Debian 12 / CentOS 7+ 等常见 Linux 均可 |
| 软件 | **Docker 24+** 与 **Docker Compose v2**（安装方法见第 1 步） |
| 网络 | 部署阶段需能访问互联网（拉取镜像与依赖）；运行阶段纯内网可用 |
| 权限 | 能使用 `sudo` 的账号 |

> Windows 服务器请安装 Docker Desktop 并启用 WSL2，命令同样适用（在 PowerShell 中执行）。

## 1. 安装 Docker（约 5 分钟）

**Ubuntu/Debian：**

```bash
curl -fsSL https://get.docker.com | sudo bash
sudo usermod -aG docker $USER   # 免 sudo 用 docker；执行后注销重新登录生效
```

验证（两条命令都有版本号输出即成功）：

```bash
docker --version
docker compose version
```

**CentOS：** 参考 Docker 官方文档安装 `docker-ce` 与 `docker-compose-plugin`，验证命令相同。

## 2. 获取平台代码

方式一（服务器有 git）：

```bash
git clone <平台仓库地址> Clinical-Data-Analysis-Platform
cd Clinical-Data-Analysis-Platform/deploy
```

方式二（离线/拷包）：把项目压缩包拷到服务器，解压后进入 `deploy` 目录：

```bash
unzip Clinical-Data-Analysis-Platform.zip
cd Clinical-Data-Analysis-Platform/deploy
```

## 3. 配置密钥（只需做一次）

复制配置模板，生成三个随机密码填进去：

```bash
cp .env.example .env
# 生成三个随机值（每条命令输出一串，复制备用）
openssl rand -hex 24    # → 填 PG_PASSWORD
openssl rand -hex 24    # → 填 MINIO_ROOT_PASSWORD
openssl rand -hex 32    # → 填 JWT_SECRET
```

用编辑器打开 `.env`（如 `nano .env`），把上面三串随机值分别填入：

```ini
PG_PASSWORD=（第一串）
MINIO_ROOT_USER=cdap-admin
MINIO_ROOT_PASSWORD=（第二串）
JWT_SECRET=（第三串）
LOG_LEVEL=INFO
# 国内服务器保留此行（加速构建）；海外可删除
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

> 没有 openssl 时，可用 `cat /dev/urandom | tr -dc A-Za-z0-9 | head -c 48` 生成。
> `.env` 就是本平台的「钥匙串」，请妥善保管、不要发给无关人员；它已被 git 屏蔽，不会进代码仓库。

## 4. 启动平台（首次约 10–20 分钟，取决于网速）

```bash
docker compose up -d --build
```

首次会下载/构建镜像。完成后查看状态，7 个容器应全部为 `running`（postgres/redis/minio 显示 `healthy`）：

```bash
docker compose ps
```

## 5. 初始化数据库 + 创建管理员（只需做一次）

```bash
# 建表
docker compose exec api alembic upgrade head

# 创建管理员账号（换成你科室的邮箱和登录密码）
docker compose exec api python -m app.scripts.create_user \
    --email admin@hospital.local --password '你的登录密码' --role admin --display-name 管理员
```

再为科室同事创建普通账号（researcher 可上传和分析；viewer 只能查看）：

```bash
docker compose exec api python -m app.scripts.create_user \
    --email doctor.zhang@hospital.local --password '初始密码' --role researcher --display-name 张医生
```

## 6. 验证部署成功

1. 浏览器访问 `http://服务器IP:8080` → 出现登录页，用第 5 步的管理员账号登录成功 ✅
2. 命令行健康检查（在服务器上执行；API 经前端 8080 端口代理）：

```bash
curl http://localhost:8080/api/v1/healthz   # {"status":"ok"}
curl http://localhost:8080/api/v1/readyz    # database/redis 均 "ok"
```

到此部署完成，日常使用见 [user-manual.md](user-manual.md)。

## 7. 日常运维

| 操作 | 命令（在 deploy 目录执行） |
|---|---|
| 启动 | `docker compose up -d` |
| 停止 | `docker compose down`（数据保留在卷中，不会丢） |
| 查看日志 | `docker compose logs -f api` / `... worker` / `... frontend` |
| 重启单个服务 | `docker compose restart api` |
| 磁盘占用 | `docker system df`；清理废弃镜像 `docker image prune` |

## 8. 备份（建议每日，可放 crontab）

```bash
# 数据库（最重要：项目、数据集元数据、分析结果都在这里）
docker compose exec postgres pg_dump -U cdap cdap | gzip > backup/cdap-$(date +%F).sql.gz

# 文件存储（上传的原始数据、报告文件）：直接备份 docker 卷
docker run --rm -v cdap_miniodata:/data -v $PWD/backup:/b alpine \
    tar czf /b/minio-$(date +%F).tar.gz -C /data .
```

建议保留最近 30 天，备份文件请拷贝到另一台机器或院内 NAS。

## 9. 升级版本

```bash
git pull                      # 或替换为新包
docker compose up -d --build  # 重建并滚动重启
docker compose exec api alembic upgrade head   # 应用数据库变更
```

回滚：切回旧代码版本重新 `up -d --build`（数据库结构向下兼容期内可直接回滚；跨大版本请先备份）。

## 10. 常见问题（FAQ）

| 现象 | 排查 |
|---|---|
| 浏览器打不开 8080 | `docker compose ps` 看 frontend 是否 running；服务器防火墙/安全组放行 8080 端口 |
| 登录一直转圈/502 | `docker compose logs api` 看 api 是否启动；确认第 5 步 `alembic upgrade head` 已执行 |
| api 容器反复重启 | 多为 `.env` 缺值或含中文引号：对照 `.env.example` 检查三个密码已填写 |
| 上传大文件失败 | 上限默认 200MB：在 `deploy/.env` 加 `MAX_UPLOAD_MB=500` 后 `docker compose up -d api` 即生效（Nginx 天花板 1024MB，超过需同步改 `frontend/nginx.conf` 的 `client_max_body_size` 并重建 frontend）；磁盘不足时 `docker system df` 清理；大文件需更多 worker 内存 |
| 分析卡住不动 | `docker compose logs -f worker` 看任务日志；单模型超时会自动标记失败（默认 15 分钟），不影响其他模型 |
| 忘记管理员密码 | 用第 5 步命令**新建**一个 admin 账号登录即可（旧账号可由新管理员禁用） |
| MinIO 文件管理台 | 浏览器访问 `http://服务器IP:9001`，账号密码为 `.env` 中的 MINIO_ROOT_USER / MINIO_ROOT_PASSWORD |

## 11. 安全基线（务必遵守）

1. 三个密钥使用随机值，**不要**用 `123456` / 科室简称之类弱口令（`ENVIRONMENT=prod` 时默认密钥会被拒绝启动）。
2. 平台仅部署于院内网络；如需对外访问，前置 Nginx + HTTPS（见 docs/21 §6）。
3. 上传数据前完成伦理审查与脱敏（去除姓名、身份证号、手机号、病历号等直接标识）。
4. 定期执行第 8 节备份并做恢复演练。
