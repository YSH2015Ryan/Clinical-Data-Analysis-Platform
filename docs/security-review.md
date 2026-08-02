# 安全审查清单（T8.4；docs/19 §7）

> 日期：2026-08-01 | 范围：越权 / 注入 / 上传 / 密钥 / 依赖 | 结论：**全项 PASS**

## 1. 上传安全

| 检查项 | 机制 | 证据（测试） | 结论 |
|---|---|---|---|
| 扩展名白名单 | `ALLOWED_EXTENSIONS={.csv,.xlsx,.xls,.tsv,.txt}`（services/datasets.py:22） | test_upload_api.py::test_bad_extension_400 | PASS |
| magic bytes 嗅探（防伪装） | `sniff_magic`：xlsx=ZIP、xls=OLE2/ZIP、文本类拒绝 NUL（services/datasets.py:42） | test_disguised_xlsx_400、test_binary_as_csv_400、test_xlsx_magic_ok | PASS |
| 超大文件 | `max_upload_mb=200` → 413（api/v1/datasets.py:66） | test_oversize_413 | PASS |
| 路径穿越 | 存储 key 服务端生成；LocalStorage 拒绝 `..`/绝对路径 | test_storage.py::test_path_traversal_rejected | PASS |
| zip slip | 不解压用户归档（xlsx 仅 pandas 只读解析） | 代码审查：无 zipfile.extract* 调用 | PASS |
| 上传权限 | `require_role("researcher")`；viewer 拒绝 | test_upload_api.py::test_viewer_403 | PASS |

## 2. 注入

| 检查项 | 机制 | 证据 | 结论 |
|---|---|---|---|
| SQL 注入 | 全部 SQLAlchemy 参数化；原生 SQL 审计 = 仅健康检查 `text("SELECT 1")`（main.py:57），无用户输入拼接 | 全仓 grep `text(/execute(f/%s` | PASS |
| derive 表达式沙箱 | simpleeval 白名单求值（engines/preprocess_steps.py:433），禁止 `__import__`/属性穿越 | test_preprocess_select_derive.py（`__import__('os').system(...)` 拒绝） | PASS |
| ORM 层隔离 | api 层禁直接操作 ORM（import-linter 契约强制） | lint-imports CI 2 kept / 0 broken | PASS |
| XSS/模板注入 | 报告模板仅渲染服务端计算值；前端 React 默认转义 | 代码审查 | PASS |

## 3. 越权（RBAC + 项目级隔离）

| 资源 | 矩阵覆盖 | 结论 |
|---|---|---|
| 项目 | viewer 创建/删除 403（test_projects_api.py） | PASS |
| 数据集 | 跨属主项目上传 404（test_upload_api.py）；quick-fix viewer 403（test_quickfix_api.py） | PASS |
| 分析运行 | viewer 创建 403；跨属主详情 403（test_analysis_api.py） | PASS |
| 比较结果 | 跨属主 403（test_analysis_api.py::test_comparison_cross_owner_403） | PASS |
| 报告 | 跨属主详情/下载 403；未 READY 400（test_report_api.py） | PASS |
| 管理端点 | /admin/plugins 非 admin 403（test_admin_plugins.py） | PASS |

## 4. 密钥与凭证

| 检查项 | 机制 | 结论 |
|---|---|---|
| 仓库无密钥 | 全仓扫描无私钥/密码/token（数据库口令走环境变量，docker-compose 本地占位不入生产） | PASS |
| 密码存储 | BCrypt（core/security.py:18） | PASS |
| JWT | HS256 + 过期（access 2h / refresh 7d） | PASS |
| 默认密钥上线防护 | **本次新增**：`ENVIRONMENT=prod` 且 `JWT_SECRET` 为开发默认值 → 启动 fail-fast（core/config.py validator；test_config.py::test_prod_rejects_default_jwt_secret） | PASS（已加固） |

## 5. 依赖安全（pip-audit + pip-licenses，2026-08-01 复扫）

- **pip-audit**：`No known vulnerabilities found`（按 docs/licenses-report.md §1 豁免 7 项：pytest 测试工具 1 + starlette 待 fastapi 升级 5 + weasyprint 无修复版 1，豁免理由与复核周期沿用原报告）。
- **pip-licenses**：GPL 族仅 scikit-survival（GPL-3.0）+ ecos（GPLv3）——R4 已知风险登记（docs/20），院内科研自用可接受；rfc3987（GPLv3+）仅 dev 依赖不进生产镜像；category_encoders 元数据误标实为 BSD；其余 MIT/BSD/Apache/MPL。
- 详见 docs/licenses-report.md（结论本次复扫一致）。

## 6. 发现与处置记录

| # | 发现 | 严重度 | 处置 |
|---|---|---|---|
| 1 | `jwt_secret` 存在开发默认值，生产误配无防护 | 中 | 已修复：ENVIRONMENT=prod fail-fast（本 PR） |
| 2 | 其余检查项均已有机制 + 测试覆盖 | — | 无需处置 |
