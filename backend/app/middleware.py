"""Request middleware that must run before FastAPI parses endpoint bodies."""

import re
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import AppError, app_error_response
from app.core.security import decode_token

_UPLOAD_PATH = re.compile(r"^/api/v1/projects/[0-9a-fA-F-]+/datasets$")
_AUTH_FAILED = AppError(code="AUTH_FAILED", status=401, message="认证失败")


def _request_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer" and credentials:
        return credentials
    return request.cookies.get("cdap_access")


class UploadAuthenticationMiddleware:
    """Authenticate uploads before their potentially large body is consumed.

    FastAPI parses multipart bodies before resolving endpoint dependencies. The
    verified claims are cached in the ASGI scope so a token that was valid when
    the request started cannot expire while the file is still being transferred.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and _UPLOAD_PATH.fullmatch(scope.get("path", ""))
        ):
            request = Request(scope, receive=receive)
            token = _request_token(request)
            if token is None:
                await app_error_response(request, _AUTH_FAILED)(scope, receive, send)
                return
            try:
                claims: dict[str, Any] = decode_token(token, expected="access")
            except AppError as exc:
                await app_error_response(request, exc)(scope, receive, send)
                return
            scope["cdap.access_claims"] = claims

        await self.app(scope, receive, send)
