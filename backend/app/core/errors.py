"""统一异常体系（docs/12 §2.3）：AppError → RFC7807 风格响应。

错误码全集见 docs/14-API-Specification.md §2（已冻结，新增 code 须先改文档）。
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        code: str,
        status: int,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.details = details or {}


def _error_payload(exc: AppError, trace_id: str) -> dict[str, Any]:
    return {
        "code": exc.code,
        "message": exc.message,
        "details": exc.details,
        "trace_id": trace_id,
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        trace_id = request.headers.get("x-request-id", "")
        return JSONResponse(status_code=exc.status, content=_error_payload(exc, trace_id))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = request.headers.get("x-request-id", "")
        wrapped = AppError(
            code="INTERNAL_ERROR",
            status=500,
            message="服务器内部错误，请稍后重试",
            details={"type": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=_error_payload(wrapped, trace_id))


# ---- 常用错误工厂（错误码与 docs/14 §2 冻结表一一对应） ----


def not_found(resource: str, resource_id: str) -> AppError:
    return AppError(
        code=f"{resource.upper()}_NOT_FOUND",
        status=404,
        message="资源不存在或已被删除",
        details={f"{resource.lower()}_id": resource_id},
    )


def forbidden(message: str = "无权访问该资源") -> AppError:
    return AppError(code="FORBIDDEN", status=403, message=message)
