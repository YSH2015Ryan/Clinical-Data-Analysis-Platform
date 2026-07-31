"""应用配置（docs/12 §2.1）：环境变量驱动，禁止代码内硬编码密钥。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 服务
    app_name: str = "cdap-backend"
    log_level: str = "INFO"

    # 基础设施
    database_url: str = "postgresql+psycopg://cdap:cdap@localhost:5432/cdap"
    redis_url: str = "redis://localhost:6379/0"

    # 对象存储（S3 兼容；storage_backend=local 时忽略）
    storage_backend: str = "local"  # local | s3
    local_storage_path: str = "./.data/storage"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "cdap"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_secure: bool = False

    # 安全（部署时必须经环境变量覆盖）
    jwt_secret: str = "dev-only-insecure-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    refresh_token_expire_days: int = 7

    # 任务
    model_timeout_s: int = 900
    max_upload_mb: int = 200

    # 排名权重（docs/09 §4.1）
    ranking_weight_primary: float = 0.6
    ranking_weight_stability: float = 0.2
    ranking_weight_secondary: float = 0.2


@lru_cache
def get_settings() -> Settings:
    return Settings()
