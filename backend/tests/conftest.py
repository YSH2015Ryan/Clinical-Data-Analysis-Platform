import os

# 测试环境默认：本地存储 + 内存级配置，不触真实基础设施
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("LOCAL_STORAGE_PATH", "./.test_storage")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://cdap:cdap@localhost:5432/cdap")
