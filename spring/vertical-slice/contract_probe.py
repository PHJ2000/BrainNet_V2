"""Compare the Spring vertical slice with the FastAPI canonical contract.

The CI job runs both applications against the same database after the backend
container has applied the current Alembic head.  Keep this probe deliberately
small and dependency-free so it can also be run from a developer checkout.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: dict[str, Any]


def call(base_url: str, method: str, path: str, token: str | None, trace_id: str | None,
         body: dict[str, Any] | None = None) -> Response:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if trace_id is not None:
        headers["X-Trace-Id"] = trace_id
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    request = Request(f"{base_url.rstrip('/')}{path}", data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return Response(
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                json.loads(raw) if raw else {},
            )
    except HTTPError as error:
        raw = error.read().decode("utf-8")
        return Response(
            error.code,
            {key.lower(): value for key, value in error.headers.items()},
            json.loads(raw) if raw else {},
        )
    except URLError as error:
        raise AssertionError(f"{method} {path} unavailable: {error}") from error


def assert_same(label: str, left: Response, right: Response, fields: tuple[str, ...] = ()) -> None:
    if left.status != right.status:
        raise AssertionError(f"{label}: status FastAPI={left.status} Spring={right.status}")
    if fields:
        for field in fields:
            if left.body.get(field) != right.body.get(field):
                raise AssertionError(
                    f"{label}: field {field!r} FastAPI={left.body.get(field)!r} "
                    f"Spring={right.body.get(field)!r}"
                )


def main() -> int:
    fastapi = os.environ.get("FASTAPI_BASE_URL", "http://127.0.0.1:8000")
    spring = os.environ.get("SPRING_BASE_URL", "http://127.0.0.1:8080")
    token = os.environ.get("JWT_TOKEN")
    if not token:
        raise AssertionError("JWT_TOKEN is required")

    project_fastapi = call(fastapi, "GET", "/projects/1", token, "contract-project")
    project_spring = call(spring, "GET", "/projects/1", token, "contract-project")
    assert_same(
        "active project",
        project_fastapi,
        project_spring,
        ("id", "name", "description", "owner_id", "is_deleted", "member_count", "node_count", "tag_count"),
    )

    deleted_fastapi = call(fastapi, "GET", "/projects/2", token, "contract-deleted")
    deleted_spring = call(spring, "GET", "/projects/2", token, "contract-deleted")
    assert_same("deleted project", deleted_fastapi, deleted_spring)
    if deleted_fastapi.body.get("code") != "NOT_FOUND":
        raise AssertionError(f"deleted project: unexpected FastAPI body {deleted_fastapi.body}")
    if deleted_spring.body.get("code") != "NOT_FOUND":
        raise AssertionError(f"deleted project: unexpected Spring body {deleted_spring.body}")

    missing_fastapi = call(fastapi, "GET", "/projects/1", None, "contract-missing-auth")
    missing_spring = call(spring, "GET", "/projects/1", None, "contract-missing-auth")
    assert_same("missing authentication", missing_fastapi, missing_spring, ("code", "message"))
    if missing_fastapi.headers.get("www-authenticate", "").lower() != "bearer":
        raise AssertionError("FastAPI missing-auth response did not challenge with Bearer")
    if missing_spring.headers.get("www-authenticate", "").lower() != "bearer":
        raise AssertionError("Spring missing-auth response did not challenge with Bearer")

    empty_fastapi = call(fastapi, "PATCH", "/projects/1/nodes/11", token, "contract-empty-patch", {})
    empty_spring = call(spring, "PATCH", "/projects/1/nodes/11", token, "contract-empty-patch", {})
    assert_same("empty patch", empty_fastapi, empty_spring, ("code", "message"))
    if not isinstance(empty_fastapi.body.get("errors"), list) or not isinstance(empty_spring.body.get("errors"), list):
        raise AssertionError("empty patch: both responses must expose validation errors")

    negative_fastapi = call(
        fastapi, "PATCH", "/projects/1/nodes/11", token, "contract-negative-version", {"expected_version": -1, "content": "x"}
    )
    negative_spring = call(
        spring, "PATCH", "/projects/1/nodes/11", token, "contract-negative-version", {"expected_version": -1, "content": "x"}
    )
    assert_same("negative version", negative_fastapi, negative_spring, ("code", "message"))

    tagged_fastapi = call(
        fastapi, "PATCH", "/projects/1/nodes/11", token, "contract-tagged-patch", {"expected_version": 0, "content": "contract"}
    )
    tagged_spring = call(
        spring, "PATCH", "/projects/1/nodes/12", token, "contract-tagged-patch", {"expected_version": 0, "content": "contract"}
    )
    assert_same("tagged patch", tagged_fastapi, tagged_spring, ("project_id", "version", "content", "tags"))
    if tagged_fastapi.body.get("tags") != [] or tagged_spring.body.get("tags") != []:
        raise AssertionError("tagged patch: canonical response must contain an empty tags array")

    missing_node_fastapi = call(fastapi, "GET", "/projects/1/nodes/999", token, "contract-missing-node")
    missing_node_spring = call(spring, "GET", "/projects/1/nodes/999", token, "contract-missing-node")
    assert_same("missing node", missing_node_fastapi, missing_node_spring, ("code", "message"))
    if missing_node_fastapi.headers.get("x-trace-id") != "contract-missing-node":
        raise AssertionError("FastAPI missing-node response lost the supplied trace id")
    if missing_node_spring.headers.get("x-trace-id") != "contract-missing-node":
        raise AssertionError("Spring missing-node response lost the supplied trace id")

    print("FastAPI/Spring canonical contract probe passed: project, auth, validation, patch, trace")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"CONTRACT PROBE FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
