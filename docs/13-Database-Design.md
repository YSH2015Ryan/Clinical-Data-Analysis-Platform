# 13. 数据库设计（Database Design）

> PostgreSQL 15。ORM SQLAlchemy 2.0 + Alembic 迁移。概念模型见 [04-Data-Model](04-Data-Model.md)。

## 1. 表 DDL（核心）

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','researcher','viewer')),
  display_name TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  settings JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE datasets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK (source_type IN ('csv','excel','fhir','omop','prepared')), -- prepared=数据准备产物（05 §8，2026-08-03）
  storage_uri TEXT NOT NULL,
  file_hash CHAR(64) NOT NULL,          -- sha256
  file_size BIGINT NOT NULL,
  encoding TEXT,
  status TEXT NOT NULL DEFAULT 'UPLOADED'
    CHECK (status IN ('UPLOADED','VALIDATING','VALIDATED','FAILED','ARCHIVED')),
  column_profile JSONB,
  preview JSONB,                         -- 前100行
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE dataset_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  version_no INT NOT NULL,
  storage_uri TEXT NOT NULL,
  transform_log JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (dataset_id, version_no)
);

CREATE TABLE quality_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('PASSED','PASSED_WITH_WARNINGS','FAILED')),
  blockers INT NOT NULL DEFAULT 0,
  warnings INT NOT NULL DEFAULT 0,
  issues JSONB NOT NULL DEFAULT '[]',
  column_profiles JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 数据准备任务（05 章 §8；2026-08-03 新增）：长表+诊断表 → 宽表数据集
CREATE TABLE preparation_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  lab_dataset_id UUID NOT NULL REFERENCES datasets(id),
  diag_dataset_id UUID NOT NULL REFERENCES datasets(id),
  decisions JSONB NOT NULL,              -- 05 §8.2 五个决策点
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED')),
  result_dataset_id UUID REFERENCES datasets(id),  -- 产出的宽表数据集
  summary JSONB,                         -- 每阶段行数变化（可审计）
  error TEXT,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE analysis_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id),
  task_type TEXT NOT NULL CHECK (task_type IN ('survival','classification','regression')),
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING','PREPROCESSING','MODELING','COMPARING','COMPLETED','FAILED','CANCELED')),
  preprocess_config JSONB NOT NULL,
  selected_models JSONB NOT NULL,
  model_params JSONB, -- 按模型 key 覆盖默认参数（docs/14 AnalysisRunCreate；2026-07-29 补列）
  task_detection JSONB,
  celery_chain_id TEXT,
  error TEXT,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE preprocess_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID UNIQUE NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  steps JSONB NOT NULL,
  feature_matrix_uri TEXT NOT NULL,
  input_hash CHAR(64) NOT NULL
);

CREATE TABLE model_plugins (
  key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  task_types TEXT[] NOT NULL,
  capability JSONB NOT NULL DEFAULT '{}',
  default_params JSONB NOT NULL DEFAULT '{}',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  entry_point TEXT NOT NULL
);

CREATE TABLE model_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  model_key TEXT NOT NULL REFERENCES model_plugins(key),
  status TEXT NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCESS','FAILED','SKIPPED')),
  metrics JSONB,
  artifacts JSONB NOT NULL DEFAULT '[]',
  explainability JSONB,
  error TEXT,
  duration_ms INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (run_id, model_key)            -- 幂等
);

CREATE TABLE comparisons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID UNIQUE NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  ranking JSONB NOT NULL,
  recommendation JSONB NOT NULL,
  comparison_charts JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  format TEXT NOT NULL CHECK (format IN ('pdf','html','markdown','docx')),
  template_key TEXT NOT NULL DEFAULT 'clinical_report_zh',
  template_version TEXT NOT NULL DEFAULT '1.0.0',  -- 模板版本化（docs/10 §3）
  storage_uri TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','READY','FAILED')),
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  action TEXT NOT NULL,
  resource_type TEXT,
  resource_id UUID,
  detail JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 2. 索引

| 表 | 索引 | 用途 |
|---|---|---|
| projects | `(owner_id) WHERE deleted_at IS NULL` | 我的项目列表 |
| datasets | `(project_id, created_at DESC)` | 项目数据集列表 |
| quality_reports | `(dataset_version_id, created_at DESC)` | 最新报告 |
| analysis_runs | `(project_id, created_at DESC)`、`(status)` | 列表 + janitor 扫描 |
| model_results | `(run_id)`、UNIQUE `(run_id, model_key)` | 结果聚合/幂等 |
| reports | `(run_id, created_at DESC)` | 报告历史 |
| audit_logs | `(user_id, created_at)`、`(resource_type, resource_id)` | 审计查询 |
| model_results | GIN `(metrics)` | 跨 run 指标检索（P2） |

## 3. 迁移与数据完整性规则

- Alembic autogenerate + 人工审查；CI 跑 `alembic upgrade head` 与 downgrade 一阶回滚测试。
- 软删除统一 `deleted_at`，查询默认过滤（SQLAlchemy event/自定义 query）。
- 外键全部显式 `ON DELETE` 行为：用户删项目 → 级联；删除用户 → 禁止（仅停用）。
- JSONB 字段写入前用 Pydantic schema 校验（DB 层兜底 CHECK 仅做存在性）。

## 4. 容量估算

- 单次 run：元数据 ~50KB + JSONB 结果 ~2MB + S3 产物 ~20MB。
- 100 用户 × 每月 20 run × 12 月 ≈ PG 60GB/年（含 GIN 索引），S3 ~500GB/年 —— 单机可承载，K8s 阶段再接外部 PG/S3。
