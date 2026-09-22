import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.trace import current_trace_id

logger = logging.getLogger(__name__)


_DEFAULT_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    428: "PRECONDITION_REQUIRED",
    429: "RATE_LIMITED",
}


def error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _request_trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", None) or current_trace_id()


def _error_body(status_code: int, detail: Any, trace_id: str) -> dict[str, Any]:
    if isinstance(detail, dict):
        code = str(detail.get("code") or _DEFAULT_CODES.get(status_code, "HTTP_ERROR"))
        message = str(detail.get("message") or "Request failed")
    else:
        code = _DEFAULT_CODES.get(status_code, "HTTP_ERROR")
        message = str(detail)

    return {
        "code": code,
        "message": message,
        "trace_id": trace_id,
    }


def _log_request_error(request: Request, status_code: int, code: str, trace_id: str) -> None:
    logger.warning(
        "request_error status=%s code=%s method=%s path=%s trace_id=%s",
        status_code,
        code,
        request.method,
        request.url.path,
        trace_id,
    )


def _log_server_error(request: Request, code: str, trace_id: str) -> None:
    logger.error(
        "request_error status=500 code=%s method=%s path=%s trace_id=%s",
        code,
        request.method,
        request.url.path,
        trace_id,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        trace_id = _request_trace_id(request)
        headers = dict(exc.headers or {})
        headers["X-Trace-Id"] = trace_id
        body = _error_body(exc.status_code, exc.detail, trace_id)
        _log_request_error(request, exc.status_code, body["code"], trace_id)
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        trace_id = _request_trace_id(request)
        body = _error_body(
            422,
            error_detail("VALIDATION_ERROR", "Request validation failed"),
            trace_id,
        )
        # Do not echo passwords, invitation tokens or rejected request bodies.
        body["errors"] = jsonable_encoder([
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ])
        _log_request_error(request, 422, body["code"], trace_id)
        return JSONResponse(
            status_code=422,
            content=body,
            headers={"X-Trace-Id": trace_id},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(request: Request, exc: SQLAlchemyError):
        trace_id = _request_trace_id(request)
        _log_server_error(request, "DB_ERROR", trace_id)
        return JSONResponse(
            status_code=500,
            content={
                "code": "DB_ERROR",
                "message": "database operation failed",
                "trace_id": trace_id,
            },
            headers={"X-Trace-Id": trace_id},
        )
