from datetime import timedelta
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core import config, security


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_required_env_fails_closed_when_value_is_missing(monkeypatch):
    monkeypatch.delenv("BRAINNET_REQUIRED_TEST_VALUE", raising=False)

    with pytest.raises(RuntimeError, match="BRAINNET_REQUIRED_TEST_VALUE environment variable is required"):
        config.required_env("BRAINNET_REQUIRED_TEST_VALUE")


def test_short_jwt_secret_fails_during_config_import():
    environment = dict(os.environ)
    environment["JWT_SECRET"] = "too-short"
    environment["PYTHONPATH"] = str(BACKEND_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "JWT_SECRET must be at least 32 bytes" in result.stderr


def test_access_token_round_trip_preserves_subject():
    token = security.create_access_token("42")

    assert security.get_current_user_id(token) == "42"


@pytest.mark.parametrize("subject", ["0", "-1", "user-42"])
def test_access_token_rejects_non_positive_numeric_subject(subject):
    with pytest.raises(ValueError, match="positive numeric user id"):
        security.create_access_token(subject)


def test_expired_access_token_is_rejected():
    token = security.create_access_token("42", expires_delta=timedelta(seconds=-1))

    with pytest.raises(HTTPException) as raised:
        security.get_current_user_id(token)

    assert raised.value.status_code == 401
    assert raised.value.headers == {"WWW-Authenticate": "Bearer"}


def test_token_without_subject_is_rejected():
    token = jwt.encode({}, security.SECRET_KEY, algorithm=security.ALGORITHM)

    with pytest.raises(HTTPException) as raised:
        security.get_current_user_id(token)

    assert raised.value.status_code == 401
