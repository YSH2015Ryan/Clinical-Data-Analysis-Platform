"""T0.5 DoD：配置加载单测。"""

from app.core.config import Settings


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.storage_backend == "local"
    assert s.model_timeout_s == 900
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
    s = Settings(_env_file=None, environment="prod", jwt_secret="s3cur3-random")  # type: ignore[call-arg]
    assert s.environment == "prod"
