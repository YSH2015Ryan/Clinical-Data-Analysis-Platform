# 依赖审计报告（首次）

> 日期：2026-07-29 | 环境：python:3.11-slim 容器，`backend/pyproject.toml`（核心 + dev，不含 deepsurv 可选组）
> 工具：pip-audit 2.x（OSV）、pip-licenses 5.x、pipdeptree

## 1. 漏洞审计（pip-audit）结论

### 已修复（调整 pyproject 约束）

| 包 | 漏洞 | 处置 |
|---|---|---|
| pyarrow | PYSEC-2026-113 | `~=17.0` → `>=23.0.1` |
| weasyprint | PYSEC-2026-2034 | `~=62.3` → `>=68.0`（PYSEC-2026-3412 暂无修复版，持续监控） |
| ecdsa（python-jose 拖入） | PYSEC-2026-1325（无修复版） | **弃用 python-jose，换 PyJWT[crypto]** |

### 豁免（CI 中 `--ignore-vuln`，附理由，每季度复核）

| 漏洞 | 包 | 豁免理由 |
|---|---|---|
| PYSEC-2026-1845 | pytest 8.x | 仅测试工具，不进生产镜像；pytest 9 生态未就绪（pytest-asyncio/schemathesis 全线 cap `<9`） |
| PYSEC-2026-161/248/249/2280/2281 | starlette 0.x | 修复仅在 starlette 1.x 线，fastapi 最新版（0.132）仍 cap `starlette<1.0`。缓解：Nginx 请求大小限制 + 上传白名单（docs/12 §2.5）；fastapi 迁移 1.x 后立即升级 |
| pip/setuptools 自身 CVE | 镜像自带 | Dockerfile 构建时 `pip install -U pip setuptools` 解决 |

## 2. 许可证审计（pip-licenses）结论

| 包 | 许可证 | 来源（pipdeptree） | 评估 |
|---|---|---|---|
| scikit-survival | **GPL-3.0** | 直接依赖（RSF/GBS/C-index） | 已知风险 R4（docs/20）：院内科研自用可接受；商业/对外分发场景启用隔离预案 |
| ecos | **GPLv3** | scikit-survival 拖入 | 同上，与 scikit-survival 绑定决策 |
| rfc3987 | GPLv3+ | jsonschema[format] ← schemathesis（**仅 dev**） | 测试工具，不进生产镜像，无分发问题 |
| psycopg / psycopg-binary | LGPL-3.0 | 直接依赖 | LGPL 动态使用合规，OK |
| pyphen | GPL2+/LGPL2+/MPL1.1 三选一 | weasyprint | 选 MPL/LGPL 路径，OK |
| nvidia-nccl-cu12 | NVIDIA Proprietary | xgboost 2.x 轮子自带 | 官方二进制再分发许可，正常使用 OK；注意其存在意味着 xgboost 含 GPU 组件 |
| category_encoders | 标称 "Other/Proprietary" | 直接依赖 | **元数据误标**，实际 BSD（已人工核对上游仓库），OK |
| 其余 ~130 包 | MIT/BSD/Apache/MPL | — | OK |

## 3. 决策汇总

1. **scikit-survival（含 ecos）保留**：平台定位院内科研工具（SaaS 不分发），GPL 可接受；若未来对外商业化，执行 R4 预案（独立 worker 进程隔离或替换实现）。此项已在 docs/20 R4 登记。
2. **JWT 库更换为 PyJWT**（pyproject 已改）。
3. CI 门禁（T0.2 落地）：`pip-audit`（含上述豁免清单）+ `pip-licenses | grep -iE 'gpl|agpl'` 出现新增 GPL 即失败，豁免清单变更必须在 PR 中说明。
4. deepsurv 可选组（torch/pycox）未在本次审计范围：R2 预案为独立镜像变体，启用该变体时需补审。

## 4. 复核计划

- 每次依赖变更：CI 自动重跑双审计
- 每季度：人工复核豁免清单（pytest/starlette/weasyprint 无修复版项）是否已有上游修复
