import asyncio
import logging
import threading
import time

import httpx
import jwt
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import allowed_origins
from app.core.log_redaction import RedactTokenQuery
from app.core.request_limits import RequestLimits
from app.core.security import ALGORITHM, SECRET_KEY, get_current_user_id
from app.core.trace import TraceIdMiddleware
from app.main import app
from app.models.auth import UserCreate
from app.services import passwords


@pytest.fixture(autouse=True)
def disable_background_workers(monkeypatch):
    monkeypatch.setenv("NODE_EVENTS_ENABLED", "false")


@pytest.mark.parametrize("password", ["short", "가" * 25, "x" * 73, "1234567\x00"])
def test_registration_rejects_unsafe_password_lengths(password):
    with pytest.raises(ValidationError):
        UserCreate(email="person@example.com", password=password)


@pytest.mark.parametrize("expires", [None, True, "9999999999", float("inf"), float("nan"), 1, -(10**400)])
def test_invalid_expiry_is_unauthorized(expires):
    claims = {"sub": "42"}
    if expires is not None:
        claims["exp"] = expires
    token = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(HTTPException) as error:
        get_current_user_id(token)
    assert error.value.status_code == 401


def test_unicode_numeric_subject_is_unauthorized():
    token = jwt.encode({"sub": "²", "exp": int(time.time()) + 60}, SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(HTTPException) as error:
        get_current_user_id(token)
    assert error.value.status_code == 401


def test_legacy_hs256_wire_format_remains_compatible():
    # Independently sign the previous sub/exp JSON format without a JWT library.
    import base64
    import hashlib
    import hmac
    import json
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")
    header = encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = encode(json.dumps({"sub": "42", "exp": int(time.time()) + 60}).encode())
    message = header + b"." + payload
    signature = encode(hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).digest())
    assert get_current_user_id((message + b"." + signature).decode()) == "42"


def test_validation_does_not_echo_password_or_token(caplog):
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            secret = "private-password-" * 10
            result = client.post("/auth/register", json={"email": "person@example.com", "password": secret})
            assert result.status_code == 422
            assert secret not in result.text + caplog.text
            assert all("input" not in item and "ctx" not in item for item in result.json()["errors"])


def test_token_query_is_redacted_in_uvicorn_records():
    record = logging.LogRecord("uvicorn.error", 20, "", 0,
                              '%s - "WebSocket %s" [accepted]',
                              ("peer", "/projects/1/ws?token=private.jwt.token&other=ok"), None)
    assert RedactTokenQuery().filter(record)
    assert "private.jwt.token" not in record.getMessage()
    assert "other=ok" in record.getMessage()


def test_redaction_preserves_uvicorn_access_formatter():
    from uvicorn.logging import AccessFormatter
    record = logging.LogRecord("uvicorn.access", 20, "", 0, '%s - "%s %s HTTP/%s" %d',
                              ("peer", "GET", "/projects/1/ws?token=private.jwt.token", "1.1", 101), None)
    RedactTokenQuery().filter(record)
    assert "private.jwt.token" not in AccessFormatter().format(record)


@pytest.mark.parametrize("origin", ["*", "https://site.example/path", "https://user@site.example"])
def test_cors_configuration_rejects_non_origins(monkeypatch, origin):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origin)
    with pytest.raises(RuntimeError):
        allowed_origins()


def test_cors_only_allows_configured_origin():
    with TestClient(app) as client:
        origin = allowed_origins()[0]
        headers = {"Origin": origin, "Access-Control-Request-Method": "POST"}
        good = client.options("/auth/login", headers=headers)
        bad = client.options("/auth/login", headers={**headers, "Origin": "https://untrusted.example"})
    assert good.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-origin" not in bad.headers


def limit_app():
    limited = FastAPI()
    limited.add_middleware(RequestLimits)
    limited.add_middleware(TraceIdMiddleware)

    @limited.post("/auth/login")
    async def login(request: Request):
        return {"length": len(await request.body())}

    @limited.get("/health")
    async def health():
        return {"status": "ok"}

    return limited


def test_auth_rate_limit_has_retry_after_and_does_not_limit_health(monkeypatch):
    monkeypatch.setenv("AUTH_REQUESTS_PER_MINUTE", "2")
    with TestClient(limit_app()) as client:
        assert client.post("/auth/login").status_code == 200
        assert client.post("/auth/login").status_code == 200
        result = client.post("/auth/login", headers={"X-Forwarded-For": "different-client"})
        assert result.status_code == 429
        assert 1 <= int(result.headers["Retry-After"]) <= 60
        assert result.json()["trace_id"] == result.headers["X-Trace-Id"]
        assert client.get("/health").status_code == 200


@pytest.mark.asyncio
async def test_chunked_auth_body_is_bounded_before_parsing(monkeypatch):
    monkeypatch.setenv("AUTH_MAX_BODY_BYTES", "16")
    async def body():
        yield b"a" * 10
        yield b"b" * 10
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=limit_app()), base_url="http://test") as client:
        assert (await client.post("/auth/login", content=body())).status_code == 413
        assert (await client.post("/auth/login", content=b"ok")).status_code == 200


@pytest.mark.asyncio
async def test_password_hashing_runs_off_event_loop(monkeypatch):
    loop_thread = threading.get_ident()
    worker_threads = []
    def slow_hash(value):
        worker_threads.append(threading.get_ident())
        time.sleep(.08)
        return "hashed"
    monkeypatch.setattr(passwords.pwd_context, "hash", slow_hash)
    ticks = 0
    task = asyncio.create_task(passwords.hash_password("password"))
    while not task.done():
        await asyncio.sleep(.005)
        ticks += 1
    assert await task == "hashed"
    assert worker_threads[0] != loop_thread
    assert ticks > 3


@pytest.mark.asyncio
async def test_password_roundtrip_and_dummy_hash():
    hashed = await passwords.hash_password("correct-password")
    assert await passwords.verify_password("correct-password", hashed)
    assert not await passwords.verify_password("wrong-password", hashed)
    assert not await passwords.verify_password("wrong-password", passwords.DUMMY_HASH)
