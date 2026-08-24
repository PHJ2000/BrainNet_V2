import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import install_error_handlers
from app.core.trace import TraceIdMiddleware


def _test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)
    install_error_handlers(app)

    @app.get("/conflict")
    async def conflict():
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT", "message": "Expected version does not match"})

    @app.get("/validation")
    async def validation(required_id: int):
        return {"id": required_id}

    class ValidationPayload(BaseModel):
        required_id: int

    @app.post("/validation-body")
    async def validation_body(payload: ValidationPayload):
        return payload

    @app.post("/unhandled")
    async def unhandled(payload: dict[str, str]):
        raise RuntimeError(f"unhandled request: {payload['attacker_value']}")

    @app.get("/database-failure")
    async def database_failure():
        raise SQLAlchemyError("database failure must not leak")

    return app


def test_http_error_has_stable_code_message_and_trace_id():
    response = TestClient(_test_app()).get("/conflict", headers={"X-Trace-Id": "contract-trace"})

    assert response.status_code == 409
    assert response.headers["X-Trace-Id"] == "contract-trace"
    assert response.json() == {
        "code": "VERSION_CONFLICT",
        "message": "Expected version does not match",
        "trace_id": "contract-trace",
    }


def test_http_exception_warning_log_has_structured_request_context_without_detail(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.errors"):
        response = TestClient(_test_app()).get(
            "/conflict",
            headers={"X-Trace-Id": "http-error-trace"},
        )

    records = [record for record in caplog.records if record.name == "app.core.errors"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].getMessage() == (
        "request_error status=409 code=VERSION_CONFLICT method=GET "
        "path=/conflict trace_id=http-error-trace"
    )
    assert "Expected version does not match" not in records[0].getMessage()
    assert response.json()["trace_id"] == "http-error-trace"


def test_validation_error_has_stable_envelope_and_trace_id():
    response = TestClient(_test_app()).get("/validation", headers={"X-Trace-Id": "validation-trace"})

    assert response.status_code == 422
    assert response.headers["X-Trace-Id"] == "validation-trace"
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["message"] == "Request validation failed"
    assert response.json()["trace_id"] == "validation-trace"
    assert response.json()["errors"]


def test_validation_warning_log_has_structured_request_context_without_raw_body(caplog):
    raw_body = "untrusted-body-value-that-must-not-be-logged"

    with caplog.at_level(logging.WARNING, logger="app.core.errors"):
        response = TestClient(_test_app()).post(
            "/validation-body",
            headers={"X-Trace-Id": "validation-body-trace"},
            json={"required_id": raw_body},
        )

    records = [record for record in caplog.records if record.name == "app.core.errors"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].getMessage() == (
        "request_error status=422 code=VALIDATION_ERROR method=POST "
        "path=/validation-body trace_id=validation-body-trace"
    )
    assert raw_body not in records[0].getMessage()
    assert response.json()["trace_id"] == "validation-body-trace"


def test_unhandled_error_uses_trace_contract_without_logging_exception_or_body(caplog):
    attacker_value = "attacker-value-that-must-not-appear-in-logs"

    with caplog.at_level(logging.WARNING, logger="app.core.trace"):
        response = TestClient(_test_app()).post(
            "/unhandled",
            headers={"X-Trace-Id": "unhandled-error-trace"},
            json={"attacker_value": attacker_value},
        )

    records = [record for record in caplog.records if record.name == "app.core.trace"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    assert records[0].getMessage() == (
        "request_error status=500 code=INTERNAL_ERROR method=POST "
        "path=/unhandled trace_id=unhandled-error-trace"
    )
    assert attacker_value not in records[0].getMessage()
    assert response.status_code == 500
    assert response.headers["X-Trace-Id"] == "unhandled-error-trace"
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "Internal server error",
        "trace_id": "unhandled-error-trace",
    }


def test_database_error_has_stable_envelope_trace_and_safe_error_log(caplog):
    with caplog.at_level(logging.ERROR, logger="app.core.errors"):
        response = TestClient(_test_app()).get(
            "/database-failure",
            headers={"X-Trace-Id": "database-error-trace"},
        )

    records = [record for record in caplog.records if record.name == "app.core.errors"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].getMessage() == (
        "request_error status=500 code=DB_ERROR method=GET "
        "path=/database-failure trace_id=database-error-trace"
    )
    assert "database failure must not leak" not in records[0].getMessage()
    assert response.status_code == 500
    assert response.headers["X-Trace-Id"] == "database-error-trace"
    assert response.json() == {
        "code": "DB_ERROR",
        "message": "database operation failed",
        "trace_id": "database-error-trace",
    }
