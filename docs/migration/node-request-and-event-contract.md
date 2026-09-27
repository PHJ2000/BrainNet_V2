# 노드 요청·이벤트 전달 계약

## 생성과 재시도

프론트의 일반·AI 생성 요청은 `Idempotency-Key`를 보낸다. 같은 사용자 동작의 전송 재시도에는 같은 키를 사용하고, 다른 동작에는 새 키를 쓴다. 백엔드는 구 클라이언트 호환을 위해 키가 없는 요청도 허용한다. 그런 요청에는 중복 생성 방지가 적용되지 않는다.

FastAPI와 Spring이 같은 DB의 `(actor_id, idempotency_key)`를 사용한다. 프로젝트 또는 요청 내용이 다르면 `409 IDEMPOTENCY_KEY_REUSED`, 같은 요청이 처리 중이면 `409 IDEMPOTENCY_IN_PROGRESS`를 반환한다. 완료 응답은 24시간 재사용한다.

처리 중 lease는 `max(120초, provider timeout + 60초)`다. 만료된 claim을 다시 획득하면 DB sequence의 새 id를 받는다. 저장 트랜잭션은 그 id를 잠그고 유효성을 확인하므로, 예전 처리자가 늦게 완료되거나 정리해도 새 claim을 변경할 수 없다. provider 대기 중에는 DB 연결을 점유하지 않는다.

노드·상속 태그·완료 응답·`node.created` Outbox는 하나의 트랜잭션에 저장한다. Spring은 노드 내용 이력과 활동 기록도 이 트랜잭션에 포함한다. provider 실패나 저장 실패 시 미완료 claim은 해제한다. 동일 버전 수정과 버전 없는 수정은 각각 409·428로 구분하며 `REQUIRE_NODE_VERSION=true`가 기본값이다. 이전 클라이언트 전환 기간에만 명시적으로 false를 설정할 수 있다.

프론트는 전송 실패, 처리 중 응답, 생성 대기열 포화 응답을 최대 두 번 더 시도한다. AI 일부 생성 후 실패하면 완료된 생성 슬롯과 미완료 요청의 키를 유지한다. provider가 명시적으로 실패한 경우에만 빈 노드로 대체하며, 재시도 중 그 선택을 바꾸지 않는다. 이 동작 상태는 현재 화면의 메모리에 있으며 탭을 새로 고친 뒤까지 보존하는 기능은 포함하지 않는다.

API와 WebSocket의 주소는 `NEXT_PUBLIC_API_BASE_URL`을 따른다. 기본값은 `http://localhost:8000`이며 Compose 개발 서버에 전달된다. production Next.js를 빌드할 때는 이 값을 빌드 환경에 설정해야 한다.

### 요청 fingerprint v1

SHA-256 입력은 UTF-8 `node-create-v1\n` 뒤에 다음 순서의 값을 붙인 것이다.

1. `content`, `ai_prompt`, `parent_id`, `depth`, `order`, `pos_x`, `pos_y`, `state`
2. null은 `-1:`. 나머지는 UTF-8 바이트 길이의 십진 문자열 + `:` + 값이다.
3. parent 0은 null, depth/order의 생략·null은 0이다.
4. 좌표의 생략·null·음의 0은 양의 0으로 정규화하고 IEEE-754 binary64의 big-endian 소문자 hex 16자리로 표현한다.

JSON 속성 순서·부동소수점 문자열·한글 인코딩 차이 때문에 두 언어의 fingerprint가 달라지는 것을 방지한다. 서로 다른 런타임이 저장한 응답은 원본 JSON 값으로 재사용한다.

**버전 배포 제약:** 이전 Spring 구현의 Jackson JSON hash와 v1은 다른 형식이다. 이전 버전의 유효한 claim이 있는 환경은 진행 중 요청을 끝내고 기존 24시간 보존 창이 지난 뒤 두 구현을 함께 갱신해야 한다. 기존 claim을 운영 DB에서 임의 삭제하지 않는다. 이 변경의 rollback 대상은 v1을 지원하는 FastAPI이며, 변경 전 서버 바이너리와 혼합 운영하는 것은 검증하지 않았다.

## Outbox → PostgreSQL 알림 → WebSocket

FastAPI worker마다 publisher와 listener가 실행된다. 어느 worker든 미발행 `node.created`, `node.updated`, `node.deleted`, `vote:cast`, `vote:confirmed`를 `FOR UPDATE SKIP LOCKED`로 가져와 `pg_notify`와 `published_at` 갱신을 같은 트랜잭션에서 실행한다. 실패한 트랜잭션은 미발행으로 남아 재시도된다. 생성·수정·삭제·활성 상태 변경·투표와 그 이벤트는 각각 같은 DB 트랜잭션에 저장한다.

알림에는 작은 Outbox 행 id만 담는다. 같은 DB를 구독하는 모든 FastAPI worker가 이벤트를 조회하고 자신의 프로젝트 room에 전달한다. 노드 이벤트는 본문 대신 node_id를 보내며 클라이언트가 인증된 GET으로 현재 상태를 가져온다. 투표 이벤트는 기존 필드에 event_id를 추가한다. worker는 최근 event_id 2,048개를 기억해 중복 알림을 억제한다. 접속자가 없는 worker는 행 조회를 생략하며 새 연결이 DB 상태를 다시 조회한다.

멤버 관리에서는 `membership.changed`, 프로젝트 삭제에서는 `project.deleted`를 같은 outbox로 전달한다.
모든 이벤트 전송 전에 현재 멤버십·프로젝트 상태·JWT 만료를 확인하고 권한이 없는 소켓을 닫는다.
유휴 연결도 15초마다 다시 확인한다. 내용 복원과 멤버 관리의 상세 범위는 [백엔드 관리 API](../backend-operations.md)를 참고한다.

PostgreSQL 알림은 커밋 시 전달되고 각 listener가 받지만 연결이 끊긴 동안의 내구성 있는 이벤트 보관을 제공하지 않는다. 그래서 listener 복구와 WebSocket 연결 시 `resync.required`를 보내며, 프론트는 DB 상태를 다시 조회한다. [PostgreSQL NOTIFY](https://www.postgresql.org/docs/15/sql-notify.html), [LISTEN 초기화 순서](https://www.postgresql.org/docs/15/sql-listen.html).

클라이언트는 알림을 100ms 단위로 묶어 한 번에 하나의 이벤트 재조회를 실행하고, 조회 중 추가 알림은 완료 후 한 번 더 조회한다. 오래된 조회 응답을 버리며 30초 주기로 상태를 다시 맞춘다. listener의 1,024개 대기열이 넘치면 resync를 요청한다. 이 방식의 보장은 **최종 노드 상태 복구**다. 모든 과거 이벤트의 재생이나 exactly-once 전달을 보장하지 않는다.

`NODE_EVENTS_ENABLED=false`로 끌 수 있다. `/health/events`에서 listener/publisher 준비 여부, 미발행 건수·최장 대기시간, 프로세스의 발행 실패 횟수를 확인한다. 기존 `/health` 응답 계약은 유지한다. FastAPI worker당 전용 DB 연결 2개가 추가로 필요하다.

`/metrics`에서 같은 상태를 Prometheus 형식으로 제공한다. 발행 후 `OUTBOX_RETENTION_DAYS`(기본 7, 최소 1)가 지난 이벤트와 만료 후 1일이 지난 claim만 정리한다. 60초마다 advisory lock을 획득한 worker가 테이블당 최대 1,000개를 정리하므로 미발행 이벤트와 유효 claim은 유지된다. 높은 지속 쓰기량에서는 정리 처리량과 저장 공간을 함께 관찰해야 한다.

전용 proxy, 모니터링 규칙, 프로젝트별 전환 및 v1 FastAPI rollback 절차는 [로컬 검증 안내](../../deploy/README.md)에 있다. 실서비스 트래픽에서의 재조회 비용과 외부 알림 수신자 설정은 운영 환경에서 확인해야 한다.
## FastAPI 생성 대기

DB 트랜잭션과 멱등성 claim을 만들기 전에 실행 자리를 확보한다. worker마다 일반/AI 대기열을 분리하며 각각 기본 동시 실행 32개, 대기 512개, 최대 대기 5초다. 포화·대기시간 초과는 `503 NODE_CREATION_BUSY`와 `Retry-After: 1`을 반환한다. 같은 동작과 키로 재시도하며 AI fallback을 실행하지 않는다. 취소 시 대기·실행 자리를 반환한다. provider I/O는 계속 DB 트랜잭션 밖에서 실행한다.
