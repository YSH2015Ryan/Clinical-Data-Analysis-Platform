# Clinical Data Analysis Platform (CDAP)

临床数据分析平台：上传临床 CSV/Excel → 自动数据校验 → 可配置预处理 → 自动识别分析任务 → 多模型并行分析 → 模型比较与推荐 → 一键生成临床分析报告（PDF / HTML / Word / Markdown）。

**面向不会编程的医生与科研人员**：全程网页操作，无需写一行代码。

## 这个项目能帮你做什么

- 把科室积累的病例随访、检验指标等 **Excel/CSV 表格直接变成统计分析结果**：哪些因素与结局相关、哪个预测模型效果最好、每个因素的影响有多大。
- 支持三类常见临床研究任务：
  - **分类**（如：是否复发、是否并发症、良恶性判别）
  - **回归**（如：住院天数、某指标数值预测）
  - **生存分析**（如：无进展生存、总生存，含 Kaplan-Meier 曲线、Cox 回归、随机生存森林）
- 最终一键生成**带图表的中文分析报告**（PDF 可打印归档、Word 可编辑、HTML 可在线查看），可直接用于课题讨论与论文素材整理。

## 特点与优势

| 特点 | 说明 |
|---|---|
| **零编程** | 网页点选完成全流程：传数据 → 确认分析任务 → 勾选模型 → 看结果 → 下载报告 |
| **数据不出院** | 部署在院内服务器，纯内网运行；不依赖任何外部云服务 |
| **无需任何 API Key** | 不使用 LLM 或任何第三方在线服务，**不需要** OpenAI/百度等 API Key 或 token；所有计算在本机完成 |
| **智能引导** | 上传后自动检查数据质量问题（缺失、异常、类型错误）并提供一键修复；自动识别分析任务类型并给出理由 |
| **多模型擂台** | 内置 14 个成熟模型（逻辑回归、随机森林、SVM、XGBoost、LightGBM、CatBoost、Lasso、Cox、随机生存森林等）同台比较，自动给出推荐与理由 |
| **结果可信** | 交叉验证计算指标，推荐结论只引用真实算出的数值；报告含方法学描述与免责声明 |
| **可解释** | 特征重要性 / SHAP 图告诉你模型依据哪些变量做判断 |
| **权限与审计** | 账号分角色（管理员/研究者/查看者），项目数据互相隔离，关键操作留痕 |

## 使用环境要求

| 项 | 要求 |
|---|---|
| 服务器 | 1 台院内 Linux 服务器（物理机/虚拟机均可），建议 4 核 CPU / 16GB 内存 / 100GB 磁盘；最低 4C8G（小数据量试用） |
| 软件 | Docker 24+ 与 Docker Compose v2（部署手册含安装命令，复制粘贴即可） |
| 网络 | **仅安装时需要联网**（下载镜像）；安装完成后可完全离线运行于院内网 |
| 使用者电脑 | 任意能访问院内网的电脑 + 现代浏览器（Chrome/Edge），无需安装任何软件 |
| 数据 | 脱敏后的 CSV/Excel（删除姓名、身份证号、手机号、病历号等直接标识），单文件 ≤200MB |

## 需要配置什么（仅部署时一次）

**只有 3 个密码类参数需要配置**，都是「自己设置的随机值」，不是向任何厂商申请的 Key：

| 参数 | 是什么 | 怎么填 |
|---|---|---|
| `PG_PASSWORD` | 平台数据库的密码 | `openssl rand -hex 24` 生成的随机串 |
| `MINIO_ROOT_PASSWORD` | 文件存储的密码 | 同上，另一个随机串 |
| `JWT_SECRET` | 登录凭证的签名密钥 | `openssl rand -hex 32` 生成的随机串 |

全部写在 `deploy/.env` 文件中（从 `.env.example` 复制而来）。**没有** LLM API Key、没有第三方 token、没有需要联网激活的许可证。

可选参数（一般用默认值即可）：上传大小上限 `MAX_UPLOAD_MB`（默认 200MB）、单模型超时 `MODEL_TIMEOUT_S`（默认 900 秒）等，完整清单见 [docs/21-Deployment.md](docs/21-Deployment.md) §3。

## 本地部署（10 分钟概要）

> 面向非技术人员的逐步图文指引（含 Docker 安装、常见问题）：**[docs/deployment-guide.md](docs/deployment-guide.md)**

```bash
cd deploy
cp .env.example .env          # 填入上面 3 个随机密钥
docker compose up -d --build  # 首次约 10–20 分钟（下载镜像）
docker compose exec api alembic upgrade head   # 建表
docker compose exec api python -m app.scripts.create_user \
    --email admin@hospital.local --password '你的登录密码' --role admin
```

浏览器访问 `http://服务器IP:8080`，用管理员账号登录即完成部署。

## 日常使用（3 分钟上手）

> 完整操作手册（含每种数据问题的处理建议）：**[docs/user-manual.md](docs/user-manual.md)**

1. **建项目** → 2. **上传数据**（自动校验，按提示一键修复）→ 3. **新建分析**（向导 5 步，推荐配置已自动填好，确认即可）→ 4. **看比较结果**（各模型指标排名与推荐理由）→ 5. **生成报告**（PDF/Word 下载）。

## 项目状态与质量

**✅ 已完成（全部里程碑 M0–M4）**

- 测试：520+ 自动化用例，总覆盖率 88%
- 性能实测：10 万行 × 50 列 × 6 模型全链路 384 秒 — [docs/perf-report.md](docs/perf-report.md)
- 安全审查（越权/注入/上传/密钥/依赖）全项通过 — [docs/security-review.md](docs/security-review.md)

## 文档导航

| 你是谁 | 看这里 |
|---|---|
| 科室管理员（要部署平台） | [docs/deployment-guide.md](docs/deployment-guide.md) |
| 医生/科研人员（要使用平台） | [docs/user-manual.md](docs/user-manual.md) |
| 开发者（要二次开发） | [docs/README.md](docs/README.md)（24 份设计文档入口）、[CLAUDE.md](CLAUDE.md) |

## 许可与合规

- 仅供科研用途，**不构成临床诊断或治疗建议**（报告内含同样免责声明）。
- 上传前请完成伦理审查与数据脱敏；仓库禁止包含任何真实/未脱敏患者数据。
- 依赖许可证审计见 [docs/licenses-report.md](docs/licenses-report.md)（scikit-survival 为 GPL-3.0，院内科研自用场景登记为已知风险 R4）。
