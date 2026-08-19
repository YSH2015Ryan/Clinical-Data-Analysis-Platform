"""应用配置（docs/12 §2.1）：环境变量驱动，禁止代码内硬编码密钥。"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_JWT_SECRET = "dev-only-insecure-secret"
_DEV_DATABASE_URL = "postgresql+psycopg://cdap:cdap@localhost:5432/cdap"
_DEV_REDIS_URL = "redis://localhost:6379/0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 服务
    app_name: str = "cdap-backend"
    log_level: str = "INFO"
    environment: str = "dev"  # dev | prod；prod 下禁止默认密钥（docs/12 §2.1，T8.4）

    # 基础设施
    database_url: str = _DEV_DATABASE_URL
    redis_url: str = _DEV_REDIS_URL

    # 对象存储（S3 兼容；storage_backend=local 时忽略）
    storage_backend: str = "local"  # local | s3
    local_storage_path: str = "./.data/storage"
    s3_endpoint: str = "http://localhost:9000"
    s3_public_endpoint: str = ""  # 浏览器可达端点（预签名重写 host，docs/12 §2.4）；空=不重写
    s3_bucket: str = "cdap"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_secure: bool = False

    # 安全（部署时必须经环境变量覆盖）
    jwt_secret: str = _DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    cookie_secure: bool = False
    auth_rate_limit: int = 5
    auth_rate_window_seconds: int = 300

    # 任务
    model_timeout_s: int = 900
    max_upload_mb: int = 200

    # 排名权重（docs/09 §4.1）
    ranking_weight_primary: float = 0.6
    ranking_weight_stability: float = 0.2
    ranking_weight_secondary: float = 0.2

    @model_validator(mode="after")
    def _prod_secret_guard(self) -> "Settings":
        """ENVIRONMENT=prod 时拒绝开发默认 JWT 密钥（fail-fast，T8.4 安全审查）。"""
        if self.environment not in {"dev", "test", "prod"}:
            raise ValueError("ENVIRONMENT 必须是 dev、test 或 prod")
        if self.environment == "prod":
            if self.jwt_secret == _DEV_JWT_SECRET:
                raise ValueError("ENVIRONMENT=prod 时必须经 JWT_SECRET 环境变量设置非默认密钥")
            if self.database_url == _DEV_DATABASE_URL or self.redis_url == _DEV_REDIS_URL:
                raise ValueError("ENVIRONMENT=prod 时必须显式设置 DATABASE_URL 和 REDIS_URL")
            if self.s3_access_key == "minioadmin" or self.s3_secret_key == "minioadmin":
                raise ValueError("ENVIRONMENT=prod 时禁止使用 MinIO 默认凭据")
            if self.storage_backend != "s3":
                raise ValueError("ENVIRONMENT=prod 必须使用 S3 兼容对象存储")
            # S3 端点在 Compose 私有网络内可走 HTTP；公网签名端点仍必须 HTTPS。
            if self.s3_secure and not self.s3_endpoint.startswith("https://"):
                raise ValueError("S3_SECURE=true 时 S3_ENDPOINT 必须使用 HTTPS")
            if not self.s3_secure and not self.s3_endpoint.startswith("http://minio:"):
                raise ValueError("生产 HTTP S3_ENDPOINT 仅允许私有 MinIO 网络端点")
            if not self.s3_public_endpoint.startswith("https://"):
                raise ValueError("ENVIRONMENT=prod 必须设置 HTTPS 的 S3_PUBLIC_ENDPOINT")
            if not self.cookie_secure:
                raise ValueError("ENVIRONMENT=prod 必须启用 Secure Cookie")
            if self.access_token_expire_minutes > 30:
                raise ValueError("生产 access token 有效期不得超过 30 分钟")
        if (
            self.max_upload_mb <= 0
            or self.auth_rate_limit <= 0
            or self.auth_rate_window_seconds <= 0
        ):
            raise ValueError("上传大小和认证限流参数必须为正数")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
