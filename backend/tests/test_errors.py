"""T0.5 DoD：RFC7807 错误响应契约（docs/14 §1）。"""

from app.core.errors import AppError, not_found, register_exception_handlers
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise not_found("dataset", "abc-123")

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("unexpected")

    return TestClient(app, raise_server_exceptions=False)


def test_app_error_rfc7807_shape() -> None:
    resp = _client().get("/boom", headers={"x-request-id": "t-1"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "DATASET_NOT_FOUND"
    assert body["message"]
    assert body["details"]["dataset_id"] == "abc-123"
    assert body["trace_id"] == "t-1"


def test_unhandled_error_mapped_to_internal() -> None:
    resp = _client().get("/crash")
    assert resp.status_code == 500
    assert resp.json()["code"] == "INTERNAL_ERROR"


def test_error_code_is_required() -> None:
    err = AppError(code="VALIDATION_ERROR", status=400, message="bad")
    assert err.status == 400
