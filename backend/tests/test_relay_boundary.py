"""The Python runtime must never expose business HTTP endpoints."""
from fastapi.routing import APIRoute, APIWebSocketRoute
from app.main import app


def test_python_surface_is_only_websocket_and_internal_diagnostics():
    http = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert http == {"/health", "/health/events", "/metrics"}
    assert {route.path for route in app.routes if isinstance(route, APIWebSocketRoute)} == {"/projects/{project_id}/ws"}
    assert app.openapi_url is None
