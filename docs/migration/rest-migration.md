# Java REST 전환

2026-09-27 기준 로컬 앱(`deploy/local-app.compose.yml`)과 개발용 루트 Compose는
nginx를 통해 아래 REST API를 Java 25 / Spring으로 연결한다. 기존 DB 스키마,
사용자 bcrypt 해시, HS256 JWT와 노드 idempotency/version/outbox 계약을 재사용한다.
DB 마이그레이션 완료 후 Spring을 시작한다.

| 영역 | Spring 구현 |
| --- | --- |
| 인증·사용자 | 회원가입, form 로그인, 내 정보, 태그별 기여 수 |
| 프로젝트 | 목록·owned 필터, 생성, 상세, PATCH/PUT, 소프트 삭제, 요약 |
| 노드 | 목록·태그 필터, 일반/AI 생성, 단건 조회, 버전 수정, 하위 트리 삭제·활성화·비활성화 |
| 태그 | CRUD, 하위 트리 부착·제거 |
| 투표·히스토리 | 투표, 확정, 히스토리 목록·상세 |

프로젝트 생성은 프로젝트·OWNER 멤버십·ACTIVE 루트를 한 트랜잭션에서 저장한다.
노드 하위 트리 변경은 부모부터 행을 잠그며, 생성 측의 부모 KEY SHARE 잠금과
함께 동시 생성·삭제를 직렬화한다. 상태 변경 시 실제 변경된 노드의 version만 증가한다.
투표는 태그 요약 행을 잠가 중복 투표와 확정 간 충돌을 처리한다.
노드·투표 이벤트는 변경 트랜잭션에서 outbox에 기록한다.

## Python에 남는 기능

- `/projects/{id}/ws`, outbox 발행·구독, `/health/events`, `/metrics`: ADR-004의 경계 유지.
- Alembic: 공유 DB의 유일한 스키마 마이그레이션 도구.
- `/projects/{id}/invite`, `/projects/join`: 원래부터 토큰 저장·검증이 없는 예시 구현.
  Java로 옮기면서 완성된 협업 기능처럼 취급하지 않는다.
- `/docs`, `/redoc`, `/openapi.json`: FastAPI가 제공하는 호환 계약 참고 문서.

일반·AI 생성은 각각 `NODE_CREATE_*`, `NODE_AI_CREATE_*` 설정으로 동시 실행과 대기열을 제한한다.
기본값은 각각 동시 실행 32, 대기 512, 최대 대기 5초이며, 초과 시 기존과 같은
503 `NODE_CREATION_BUSY` 및 `Retry-After: 1`을 반환한다. 대기 중 DB 연결이나 idempotency 키를 점유하지 않는다.

## 호환성 및 명시적인 차이

- 응답은 기존 snake_case 필드를 유지한다. 프로젝트 목록·생성·수정의 집계 필드는 null이며,
  상세 응답에는 node_count/tag_count가 포함된다. 소프트 삭제와 목록의 기존 동작을 유지한다.
- 태그 응답은 실제 FastAPI `TagOut` 스키마와 동일하다. 스키마에 없는 `nodes` 필드는 추가하지 않는다.
- 노드 태그 필터는 여러 태그가 일치해도 같은 노드를 한 번만 반환한다. 잘못된 태그 ID는 422다.
- Java는 DB 컬럼 길이를 초과한 입력과 신규 가입 비밀번호의 UTF-8 72바이트 초과를 422로 거부한다.
  기존 bcrypt 해시를 재해싱하거나 사용자 데이터를 변경하지 않는다.
- 브라우저 CORS 기본 허용 주소는 `http://localhost:3000`, `http://127.0.0.1:3000`이다.
  직접 실행 시 `CORS_ALLOWED_ORIGINS`에 쉼표로 구분한 주소를 지정할 수 있다.
- 타임스탬프의 UTC 표기는 런타임에 따라 `Z` 또는 `+00:00`일 수 있다.

## 실행·롤백

기존 시작 명령을 사용한다. 로컬 앱은 `./deploy/start-local.ps1`, 개발은 `docker compose up --build -d`다.
이제 API 공개 포트는 nginx가 소유하고 내부 FastAPI와 Spring 포트는 호스트에 공개하지 않는다.
노드의 일부 쓰기만 다른 런타임에 남지 않도록 REST 전체를 함께 전환한다.

로컬 `.env.local` 또는 개발 `.env`에서 다음 설정을 변경한 뒤 동일한 Compose 시작 명령을 실행한다.

```dotenv
# Spring 기본값
BRAINNET_REST_UPSTREAM=spring
# FastAPI로 REST 전체 롤백할 때는 위 값을 backend로 변경
```

`X-BrainNet-Writer` 응답 헤더로 실제 처리 런타임을 확인할 수 있다.
롤백은 라우팅만 변경하며 DB downgrade나 볼륨 삭제를 하지 않는다.
nginx 교체 전 진행 중인 쓰기 요청이 끝난 뒤 새 소유자로 트래픽을 보내야 한다.
이 설정은 로컬용이며 운영 트래픽의 무중단 소유권 이전 절차를 대신하지 않는다.

별도 검증 Compose에서는 `./deploy/set-canary.ps1 -ProjectIds 1`이 프로젝트 1의
전체 노드 경로를 전환한다. `-AllRest`는 인증·사용자·프로젝트 REST 전체를 전환한다.
인수 없이 실행하면 FastAPI로 롤백한다. WebSocket과 예시 초대·참여 경로는 항상 FastAPI다.

## 검증

- PostgreSQL 15 Testcontainers 통합 테스트: 기존 19개 + 새 REST 테스트 9개 + 생성 제한 테스트 3개, 총 31개 통과.
- 새 테스트는 Alembic head SQL의 실제 FK·enum·NOT NULL·unique 제약을 사용한다.
- 검증 항목: bcrypt 로그인, JWT 보호, 생성 트랜잭션 롤백, 소유자/멤버 권한,
  노드 상태·버전·삭제·outbox, 루트 충돌 롤백, 태그 상속·프로젝트 격리,
  동시 중복 투표, 확정·히스토리·outbox, CORS와 422 오류 계약.
- `rest_probe.py`: 실제 프록시에서 REST 전환/롤백, Java↔Python 가입·로그인·JWT,
  공통 조회 응답과 WebSocket node.created/updated/deleted 전달을 검사한다.
  `deploy/verify-local.ps1`에 양방향 실행을 포함했다. 별도 로컬 Compose DB에서 Spring 전환과 FastAPI 롤백 모두 통과했다.

직접 probe를 실행할 때 필요한 환경변수:

```text
ALLOW_TEST_DATABASE_RESET=1   # 반드시 별도 검증 DB 사용; probe 자체는 테이블 초기화 안 함
PROXY_BASE_URL=http://proxy:8080
FASTAPI_BASE_URL=http://fastapi:8000
SPRING_BASE_URL=http://spring:8080
REST_EXPECTED_OWNER=spring    # 검증 Compose 롤백: fastapi / 로컬 Compose 롤백: backend
```

실제 OpenAI staging, production shadow/canary, 1~6시간 soak 및 자원/JFR gate는
이번 로컬 REST 전환 검증으로 대체되지 않는다. WebSocket Java 전환은 별도 ADR과 측정이 필요하다.
