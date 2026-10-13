> 현재 실행·마이그레이션 기준은 [Spring 작업 공간 통합](../../docs/migration/spring-workspace.md)입니다. 아래 내용은 이전 단계의 기록이며 Python REST 롤백·Alembic 시작 절차는 현재 구성에 적용하지 않습니다.

# BrainNet Spring REST backend

Java 25 / Spring Boot 4.1 service implementing the shared Alembic schema and
HS256 JWT contract. The module keeps its original `vertical-slice` path.
Local and development Compose route REST to Spring by default. This does not
claim that production provider/canary/soak gates have been completed.

Implemented routes:

- Health, registration, form login, current user and tag contribution summaries
- Project list/create/detail/update/delete and owner summary
- Node list (optional tag filter), regular/AI create, get, versioned patch,
  subtree delete, activate and deactivate
- Tag CRUD and subtree attach/detach
- Vote cast/confirm and history list/detail

Node and vote mutations commit their outbox events in the same transaction.
FastAPI continues delivering those events to WebSocket clients. Alembic, the
WebSocket endpoint, event diagnostics and the unfinished invite/join examples
remain Python-owned. This service never initializes or migrates the schema.

See [REST migration](../../docs/migration/rest-migration.md) for ownership,
compatibility differences, local rollback and remaining production gates.

Required configuration:

```text
JWT_SECRET                       # at least 32 bytes
SPRING_DATASOURCE_URL            # jdbc:postgresql://...
SPRING_DATASOURCE_USERNAME
SPRING_DATASOURCE_PASSWORD
```

Local verification (Docker is required for the Testcontainers PostgreSQL and
Mailpit integration tests; mail is captured locally):

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

The REST integration tests use `src/test/resources/alembic-head.sql`, generated
from Alembic head. CI compares it with a fresh export. After a schema change:

```bash
cd backend
PYTHONPATH=. alembic upgrade head --sql | sed -E 's/[[:space:]]+$//' | perl -0pe 's/\n+\z/\n/' > ../spring/vertical-slice/src/test/resources/alembic-head.sql
```

`rest_probe.py` verifies cross-runtime bcrypt/JWT compatibility, shared reads,
proxy ownership and WebSocket delivery after cutover and rollback. Run it only
against a disposable database with the environment in the migration document.
