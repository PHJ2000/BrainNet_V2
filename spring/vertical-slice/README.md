# BrainNet Spring vertical slice

This module is the ADR-002 first production-shaped slice. It is an independent
Spring Boot 4.1 / Java 25 service, but it is not a proxy cutover: FastAPI keeps
ownership of every route until the shadow, canary, soak, and rollback gates are
completed.

Implemented routes:

- `GET /health`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/nodes/{node_id}`
- `PATCH /projects/{project_id}/nodes/{node_id}` with `expected_version`

The service reads the Alembic public schema, validates the same HS256 JWT
(`sub` is a positive numeric user id), checks project membership, and uses an
atomic PostgreSQL conditional update for optimistic concurrency. It does not
run migrations or initialize tables. Start it only against a database already
at Alembic head. AI, POST node creation, and WebSocket routes remain in FastAPI.

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
