# BrainNet Spring vertical slice

This module is the ADR-002 first production-shaped slice. It is an independent
Spring Boot 4.1 / Java 25 service, but it is not a proxy cutover: FastAPI keeps
ownership of every route until the shadow, canary, soak, and rollback gates are
completed.

Implemented routes:

- `GET /health`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/nodes/{node_id}`
- `POST /projects/{project_id}/nodes` for regular and `ai_prompt` node creation
- `PATCH /projects/{project_id}/nodes/{node_id}` with `expected_version`

The service reads the Alembic public schema, validates the same HS256 JWT
(`sub` is a positive numeric user id), checks project membership, and uses an
atomic PostgreSQL conditional update for optimistic concurrency. Node creation
uses the Alembic-head `idempotency_request` and `outbox_event` tables in the
same database transaction; AI provider calls happen before that transaction
and a successful AI node is stored as `GHOST`. It does not run migrations or
initialize tables. Start it only against a database already at Alembic head.
The project WebSocket route (`/projects/{project_id}/ws`) remains owned by
FastAPI; this service does not attempt a WebSocket cutover.

This module is not itself a production proxy cutover. Before routing the live
POST path here, run the staging provider contract, shadow/canary, soak,
resource/JFR, and rollback gates in `docs/migration/adr-rollout-runbook.txt`.

Required configuration:

```text
JWT_SECRET                       # at least 32 bytes
SPRING_DATASOURCE_URL            # jdbc:postgresql://...
SPRING_DATASOURCE_USERNAME
SPRING_DATASOURCE_PASSWORD
```

Local verification (Docker is required for the Testcontainers PostgreSQL
integration test):

```bash
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e TESTCONTAINERS_RYUK_DISABLED=true \
  -e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":/workspace -w /workspace \
  maven:3.9.11-eclipse-temurin-25 \
  mvn -B -f spring/vertical-slice/pom.xml test
```

Build the runtime image from the repository root:

```bash
docker build --file spring/vertical-slice/Dockerfile --tag brainnet-spring-vertical-slice .
```
