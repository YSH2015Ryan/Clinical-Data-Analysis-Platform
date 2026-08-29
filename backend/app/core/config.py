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
    model_timeout_s: int = 900   # 单个模型任务的硬超时（秒），超时后 worker SIGKILL
    run_timeout_s: int = 7200    # 整个分析 run 的超时（秒，默认 2 小时）
    # T6.5：软时间限制按模型分档（软限内抛异常 → 任务自我标记失败并给出分类原因，
    # 不再等 janitor 5 分钟轮询）；0 < default ≤ heavy，超过硬超时的部分在使用处钳制。
    model_soft_time_limit_default: int = 480  # 轻量模型（logreg/lasso/coxph/km 等）
    model_soft_time_limit_heavy: int = 840    # 重模型（rsf/gbs/svm/boosting 家族等）
    max_upload_mb: int = 200

    # LLM 部署层（T6.6，docs/12 §2.1；运行层策略/开关/key 在 DB admin_settings，管理员界面调整）
    ollama_base_url: str = "http://localhost:11434"  # compose 内为 http://ollama:11434
    ollama_model: str = "qwen2.5:7b"
    openai_model: str = "gpt-4o-mini"
    llm_default_choice: str = "auto"  # auto | local | cloud
    llm_cloud_enabled: bool = False  # 部署层云端总闸：false 时云端功能一律不可用
    # admin_settings 敏感字段 Fernet 密钥；空 = dev 用 JWT_SECRET 派生（prod 必须显式设置）
    settings_encryption_key: str = ""

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
            if not self.settings_encryption_key:
                raise ValueError("ENVIRONMENT=prod 必须设置 SETTINGS_ENCRYPTION_KEY（Fernet 密钥）")
        if (
            self.max_upload_mb <= 0
            or self.auth_rate_limit <= 0
            or self.auth_rate_window_seconds <= 0
        ):
            raise ValueError("上传大小和认证限流参数必须为正数")
        # 仅校验分档顺序；与 model_timeout_s 的关系在使用处动态钳制
        # （MODEL_TIMEOUT_S 可能被部署调低，软限随之下探，见 _model_soft_time_limit）。
        if not (0 < self.model_soft_time_limit_default <= self.model_soft_time_limit_heavy):
            raise ValueError("软时间限制须满足 0 < default ≤ heavy")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
