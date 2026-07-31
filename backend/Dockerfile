FROM python:3.11-slim AS base

# LightGBM 运行时依赖 OpenMP 库（slim 镜像不含 libgomp，import 即 OSError）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 修复镜像自带 pip/setuptools CVE（docs/licenses-report.md §1；setuptools>=83 = PYSEC-2026-3447 修复版）
RUN pip install --no-cache-dir -U pip "setuptools>=83.0.0"

WORKDIR /app

# 依赖层（利用构建缓存）；PIP_INDEX_URL 可在网络受限环境覆盖为镜像源
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY pyproject.toml ./
COPY app/__init__.py ./app/__init__.py
# 先仅安装依赖（不含 dev；测试镜像用 --target dev）
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} . \
    && pip install --no-cache-dir --index-url ${PIP_INDEX_URL} alembic

FROM base AS dev
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} ".[dev]"

FROM base AS prod
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
# 非 root 运行（docs/21 §6）
RUN useradd -r -u 10001 cdap && chown -R cdap /app
USER cdap
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
