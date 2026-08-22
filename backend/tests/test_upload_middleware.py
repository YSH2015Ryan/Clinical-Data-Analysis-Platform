"""Upload authentication must complete before a multipart body is consumed."""

from typing import Any

from app.core.security import create_token
from app.middleware import UploadAuthenticationMiddleware


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/projects/00000000-0000-0000-0000-000000000000/datasets",
        "raw_path": b"/api/v1/projects/00000000-0000-0000-0000-000000000000/datasets",
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }


async def test_unauthorized_upload_is_rejected_without_reading_body() -> None:
    body_read = False
    app_called = False
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"large body", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        nonlocal app_called
        app_called = True

    middleware = UploadAuthenticationMiddleware(app)
    await middleware(_scope(), receive, send)  # type: ignore[arg-type]

    assert body_read is False
    assert app_called is False
    assert messages[0]["status"] == 401


async def test_valid_upload_claims_are_cached_before_body_parsing() -> None:
    token = create_token("00000000-0000-0000-0000-000000000001", "researcher", "access")
    cached_claims: dict[str, Any] | None = None

    async def receive() -> dict[str, Any]:
        raise AssertionError("middleware must not consume the upload body")

    async def send(message: dict[str, Any]) -> None:
        raise AssertionError(f"unexpected middleware response: {message}")

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        nonlocal cached_claims
        cached_claims = scope.get("cdap.access_claims")

    headers = [(b"authorization", f"Bearer {token}".encode())]
    middleware = UploadAuthenticationMiddleware(app)
    await middleware(_scope(headers), receive, send)  # type: ignore[arg-type]

    assert cached_claims is not None
    assert cached_claims["sub"] == "00000000-0000-0000-0000-000000000001"
