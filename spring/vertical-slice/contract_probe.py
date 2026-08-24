"""Compare the Spring vertical slice with the FastAPI canonical contract.

The CI job runs both applications against the same database after the backend
container has applied the current Alembic head.  Keep this probe deliberately
small and dependency-free so it can also be run from a developer checkout.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: dict[str, Any]


def call(base_url: str, method: str, path: str, token: str | None, trace_id: str | None,
         body: dict[str, Any] | None = None, idempotency_key: str | None = None) -> Response:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if trace_id is not None:
        headers["X-Trace-Id"] = trace_id
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
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


def assert_body_same(label: str, left: Response, right: Response) -> None:
    assert_same(label, left, right)
    if left.body != right.body:
        raise AssertionError(f"{label}: body FastAPI={left.body!r} Spring={right.body!r}")
    for header in ("x-trace-id",):
        if left.headers.get(header) != right.headers.get(header):
            raise AssertionError(
                f"{label}: header {header!r} FastAPI={left.headers.get(header)!r} "
                f"Spring={right.headers.get(header)!r}"
            )


def run_spring_concurrency_probe(base_url: str, token: str) -> None:
    def patch(index: int) -> int:
        return call(
            base_url,
            "PATCH",
            "/projects/1/nodes/13",
            token,
            f"contract-concurrency-{index}",
            {"expected_version": 0, "content": f"writer-{index}"},
        ).status

    with ThreadPoolExecutor(max_workers=100) as pool:
        statuses = list(pool.map(patch, range(100)))
    counts = Counter(statuses)
    if counts != Counter({200: 1, 409: 99}):
        raise AssertionError(f"100-writer Spring concurrency: unexpected statuses {counts}")

    final = call(base_url, "GET", "/projects/1/nodes/13", token, "contract-concurrency-final")
    if final.status != 200 or final.body.get("version") != 1:
        raise AssertionError(f"100-writer Spring concurrency: final response {final.status} {final.body}")


def run_spring_node_creation_probe(base_url: str, token: str) -> None:
    body = {"content": "contract-created", "parent_id": 12, "depth": 2, "order": 4,
            "pos_x": 4.5, "pos_y": 5.5}
    first = call(base_url, "POST", "/projects/1/nodes", token, "contract-node-create",
                 body, "contract-node-idempotency")
    second = call(base_url, "POST", "/projects/1/nodes", token, "contract-node-retry",
                  body, "contract-node-idempotency")
    if first.status != 201 or second.status != 201:
        raise AssertionError(f"node create idempotency: unexpected statuses {first.status} {second.status}")
    if first.body != second.body:
        raise AssertionError(f"node create idempotency: retry body differs {first.body} {second.body}")
    created = first.body[0] if isinstance(first.body, list) and first.body else {}
    if created.get("state") != "GHOST" or created.get("parent_id") != 12 or created.get("tags") != [101]:
        raise AssertionError(f"node create contract: unexpected response {first.body}")

    reused = call(base_url, "POST", "/projects/1/nodes", token, "contract-node-reused",
                  {"content": "different", "parent_id": 12}, "contract-node-idempotency")
    if reused.status != 409 or reused.body.get("code") != "IDEMPOTENCY_KEY_REUSED":
        raise AssertionError(f"node create idempotency reuse: unexpected response {reused.status} {reused.body}")

    unconfigured_ai = call(base_url, "POST", "/projects/1/nodes", token, "contract-ai-unconfigured",
                           {"ai_prompt": "contract", "parent_id": 12}, "contract-ai-idempotency")
    if unconfigured_ai.status != 503 or unconfigured_ai.body.get("code") != "AI_PROVIDER_NOT_CONFIGURED":
        raise AssertionError(f"AI provider gate: unexpected response {unconfigured_ai.status} {unconfigured_ai.body}")


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
    assert_body_same("empty patch", empty_fastapi, empty_spring)
    if not isinstance(empty_fastapi.body.get("errors"), list) or not isinstance(empty_spring.body.get("errors"), list):
        raise AssertionError("empty patch: both responses must expose validation errors")

    negative_fastapi = call(
        fastapi, "PATCH", "/projects/1/nodes/11", token, "contract-negative-version", {"expected_version": -1, "content": "x"}
    )
    negative_spring = call(
        spring, "PATCH", "/projects/1/nodes/11", token, "contract-negative-version", {"expected_version": -1, "content": "x"}
    )
    assert_body_same("negative version", negative_fastapi, negative_spring)

    conflict_fastapi = call(
        fastapi, "PATCH", "/projects/1/nodes/11", token, "contract-version-conflict", {"expected_version": 99, "content": "x"}
    )
    conflict_spring = call(
        spring, "PATCH", "/projects/1/nodes/12", token, "contract-version-conflict", {"expected_version": 99, "content": "x"}
    )
    assert_body_same("version conflict", conflict_fastapi, conflict_spring)
    if conflict_fastapi.status != 409 or conflict_fastapi.body.get("code") != "NODE_VERSION_CONFLICT":
        raise AssertionError(f"version conflict: unexpected response {conflict_fastapi.status} {conflict_fastapi.body}")

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

    run_spring_node_creation_probe(spring, token)
    run_spring_concurrency_probe(spring, token)

    print("FastAPI/Spring canonical contract probe passed: project, auth, validation, patch, conflict, trace, node create/idempotency/outbox, 100-writer concurrency")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"CONTRACT PROBE FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
