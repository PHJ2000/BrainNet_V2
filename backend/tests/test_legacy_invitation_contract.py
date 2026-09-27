from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import install_error_handlers
from app.core.security import get_current_user_id
from app.routers.projects import router


def test_legacy_invitation_endpoints_fail_closed_without_touching_database():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: "42"
    client = TestClient(app)
    for path in ("/projects/1/invite?email=other@example.com", "/projects/join?token=anything"):
        response = client.post(path)
        assert response.status_code == 410
        assert response.json()["code"] == "INVITATIONS_REQUIRE_SPRING"
