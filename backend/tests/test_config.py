"""T0.5 DoD：配置加载单测。"""

from app.core.config import Settings


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.storage_backend == "local"
    # hotfix 4b45c3a：972k 行 lasso 实测需 22 分钟，硬超时提到 70 分钟
    assert s.model_timeout_s == 4200
    assert s.run_timeout_s == 10800
    # T6.5 软限分档：default ≤ heavy 且低于硬超时（留 SIGKILL 前分类机会）
    assert 0 < s.model_soft_time_limit_default <= s.model_soft_time_limit_heavy < s.model_timeout_s
    assert s.max_upload_mb == 200
    assert s.jwt_algorithm == "HS256"


def test_settings_env_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MODEL_TIMEOUT_S", "300")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.model_timeout_s == 300
    assert s.log_level == "DEBUG"


def test_prod_rejects_default_jwt_secret() -> None:
    """T8.4：ENVIRONMENT=prod 时默认密钥 fail-fast（docs/12 §2.1）。"""
    import pytest

    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, environment="prod")  # type: ignore[call-arg]
    # 非默认密钥放行
    s = Settings(
        _env_file=None,
        environment="prod",
        jwt_secret="s3cur3-random",
        database_url="postgresql+psycopg://cdap:secret@postgres:5432/cdap",
        redis_url="redis://:secret@redis:6379/0",
        storage_backend="s3",
        s3_endpoint="http://minio:9000",
        s3_public_endpoint="https://storage.example.com",
        s3_access_key="cdap-storage",
        s3_secret_key="storage-secret",
        cookie_secure=True,
        settings_encryption_key="gQ9k2mXwJvR8sY3hN5bT6cL1zP4eU7aF0oK9iD2xM8s=",
    )  # type: ignore[call-arg]
    assert s.environment == "prod"
