from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app


def test_health_has_generated_trace_id():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend-legacy"}
    UUID(response.headers["X-Trace-Id"])


def test_health_preserves_caller_trace_id():
    response = TestClient(app).get("/health", headers={"X-Trace-Id": "migration-contract-123"})

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == "migration-contract-123"
