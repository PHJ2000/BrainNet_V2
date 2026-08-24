import contextvars
import logging
import re
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


trace_id_context: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = logging.getLogger(__name__)


def current_trace_id() -> str:
    return trace_id_context.get() or str(uuid.uuid4())


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        requested_trace_id = request.headers.get("X-Trace-Id", "")
        trace_id = (
            requested_trace_id
            if _TRACE_ID_PATTERN.fullmatch(requested_trace_id)
            else str(uuid.uuid4())
        )
        request.state.trace_id = trace_id
        token = trace_id_context.set(trace_id)
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.warning(
                    "request_error status=500 code=INTERNAL_ERROR method=%s path=%s trace_id=%s",
                    request.method,
                    request.url.path,
                    trace_id,
                )
                response = JSONResponse(
                    status_code=500,
                    content={
                        "code": "INTERNAL_ERROR",
                        "message": "Internal server error",
                        "trace_id": trace_id,
                    },
                )
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            trace_id_context.reset(token)
