# ADR-005: Spring 프로젝트·노드 API의 단계적 운영 전환

- 상태: Proposed
- 작성일: 2026-08-29
- 대상: Spring vertical slice의 프로젝트·노드 HTTP 경로와 FastAPI WebSocket 연동
- 선행 결정: ADR-002는 프로젝트·노드 트랜잭션 코어의 Spring 전환을 채택했고, ADR-004는 일반·AI
  노드 생성을 하나의 Spring write owner로 묶고 프로젝트 WebSocket은 FastAPI에 유지하기로 결정했다.

## 결정 질문

구현과 통합 검증이 끝난 Spring 프로젝트·노드 API를 한 번에 운영 트래픽으로 전환할 것인가, 아니면
외부 provider, event 전달, resource 안정성 및 rollback을 독립적으로 입증한 뒤 단계적으로 전환할
것인가?

## 현재 상태와 범위

PR #4까지 머지된 Spring vertical slice는 다음 경로를 구현한다.

- `GET /projects/{project_id}`
- `GET /projects/{project_id}/nodes/{node_id}`
- `POST /projects/{project_id}/nodes`의 일반 생성과 `ai_prompt` AI 생성
- `PATCH /projects/{project_id}/nodes/{node_id}`

JWT·멤버십, optimistic concurrency, idempotency와 outbox의 PostgreSQL 통합 검증은 완료되었다.
그러나 현재 FastAPI가 운영 경로를 계속 소유하며, Spring module 자체는 proxy cutover가 아니다.
`/projects/{project_id}/ws`는 ADR-004에 따라 FastAPI가 계속 소유한다.

다음 항목은 아직 운영 전환 완료의 증거가 아니다.

- mock provider를 사용한 부하·장애 검증
- 로컬 proxy cutover/rollback smoke
- 짧은 통합 테스트와 CI 성공
- outbox row가 transaction과 함께 생성된다는 DB 검증

운영 전환에는 실제 OpenAI 연결, Spring commit 이후 WebSocket event 전달, 장시간 resource 안정성,
실제 proxy rollback과 backlog recovery 증거가 추가로 필요하다.

## 선택지

1. **일괄 전환**: 모든 대상 HTTP 경로를 한 번에 Spring으로 전환하고 장애 시 전체를 FastAPI로
   되돌린다.
2. **단계적 전환**: 사전 등록된 gate를 순서대로 통과한 뒤 shadow, canary, soak와 전체 cutover를
   진행한다.
3. **장기 이중 write**: FastAPI와 Spring이 같은 요청을 동시에 처리하고 결과를 비교한다.

## 결정

선택지 2인 단계적 전환을 채택한다. 선택지 1은 장애가 OpenAI, proxy, JVM resource, DB, outbox,
pub/sub 또는 WebSocket consumer 중 어디에서 발생했는지 분리하기 어렵다. 선택지 3은 node와 outbox의
중복 생성 및 write conflict를 만들 수 있으므로 채택하지 않는다.

전환 과정에서도 다음 ownership 원칙을 유지한다.

1. 같은 시점에 하나의 route에는 하나의 write owner만 둔다.
2. `POST /projects/{project_id}/nodes`는 request body의 `ai_prompt` 유무로 나누지 않는다. 일반·AI
   생성은 같은 backend로 함께 전환한다.
3. 운영 POST를 FastAPI와 Spring에 동시에 보내는 shadow는 금지한다. POST 비교는 write가 차단된
   dry-run, 격리 DB 또는 synthetic request로만 수행한다.
4. Spring은 FastAPI process-local WebSocket connection set을 직접 호출하지 않는다. commit된
   outbox event를 publisher와 외부 pub/sub를 통해 전달하고 FastAPI가 소비한다.
5. Alembic이 schema owner로 남는다. 운영 rollback은 proxy route를 FastAPI로 되돌리며 expand된
   schema를 유지하고 Alembic downgrade를 실행하지 않는다.

## 단계와 진입·종료 gate

각 단계의 수치 기준, 실행 환경, 관찰 시간과 rollback 담당자는 실행 전에 운영 전환 Issue에
사전 등록한다. 실패한 기준은 결과를 본 뒤 완화하지 않으며, 다음 단계로 진행하려면 해당 단계의
필수 gate를 모두 통과해야 한다.

### 0. 전환 준비

진입 조건은 ADR-004 구현과 최신 `main` CI가 통과한 상태다. 다음을 준비하면 종료한다.

- Spring/FastAPI를 즉시 전환할 수 있는 endpoint 단위 proxy switch
- Spring과 FastAPI의 request/trace ID, HTTP 오류율·latency, DB pool, JVM, outbox 지표
- rollback 대상 FastAPI의 health와 현재 schema 호환성 확인
- 배포, rollback, outbox backlog recovery 절차와 담당자
- API와 WebSocket을 함께 검사하는 cutover/rollback smoke

### 1. staging 환경의 실제 OpenAI 계약

Spring staging 배포가 실제 OpenAI API를 제한된 요청량으로 호출하여 다음을 통과하면 종료한다.

- TLS, 인증, SDK 응답 parsing과 정상 AI node 생성
- 429의 bounded retry/backoff와 최종 오류 계약
- provider timeout과 client 취소 시 작업 종료 및 connection 회수
- 실패·취소 시 node와 outbox의 부분 commit 0건
- 같은 idempotency key 재시도 시 node와 outbox가 각각 최대 1건으로 수렴
- provider 회복 후 새 요청이 정상 처리됨

실제 OpenAI 비용과 rate limit을 통제하기 위해 고정된 소량 dataset과 요청 상한을 사용한다.

### 2. outbox·pub/sub·FastAPI WebSocket 연결

live POST canary 전에 다음 event 경로를 완성한다.

```text
Spring transaction commit
  -> outbox publisher
  -> external pub/sub
  -> FastAPI consumer
  -> /projects/{project_id}/ws broadcast
```

다음을 통과하면 종료한다.

- rollback된 transaction의 event는 발행되지 않음
- publisher 재시작 후 미발행 event를 재처리함
- at-least-once delivery의 중복을 consumer가 같은 event ID로 억제함
- pub/sub 또는 FastAPI 중단 후 backlog가 유실 없이 회복됨
- project가 다른 WebSocket client로 event가 누출되지 않음
- event publish lag와 backlog를 관찰하고 경보할 수 있음

pub/sub 제품 선택, delivery 보존 시간, retry 횟수와 dead-letter 정책은 이 ADR의 구현 Issue에서
결정하고 기록한다.

### 3. shadow와 synthetic 검증

GET은 응답 status, body와 권한 오류 계약을 legacy와 비교할 수 있다. PATCH·POST는 운영 DB에
이중 write하지 않고 격리 환경 또는 write 차단 방식으로 계약을 비교한다.

다음을 통과하면 종료한다.

- 정상, 인증 실패, 멤버십 실패, validation과 conflict 응답 계약 일치
- 일반 node와 AI node의 필수 response field 일치
- Spring shadow가 운영 DB, outbox와 WebSocket에 side effect를 남기지 않음
- proxy route별 Spring 전환과 FastAPI 복귀 smoke 성공

### 4. 제한적 canary

내부 allowlist 또는 안정적인 project/user routing key로 Spring traffic을 제한한다. 관련 요청이
요청마다 임의로 다른 backend에 분산되지 않도록 같은 ownership 단위에는 같은 backend를 적용한다.

canary는 내부 사용자에서 시작해 사전 등록한 비율로만 확대한다. 다음 조건 중 하나라도 발생하면
즉시 확대를 중단하고 FastAPI로 rollback한다.

- 데이터 불일치, 중복 node 또는 잘못된 project event
- 사전 등록한 HTTP 오류율·latency budget 초과
- OOM, process restart, 지속적인 DB pool 고갈 또는 처리 불능
- outbox backlog·publish lag가 한도를 넘고 관찰 시간 안에 회복되지 않음
- OpenAI 장애가 정의한 429·timeout 계약 밖으로 전파됨

### 5. resource 검증과 1~6시간 soak

Spring은 `-Xmx512m`를 적용하고 실제 일반·AI 요청과 event fan-out을 포함한 대표 workload로 최소
1시간, 최대 6시간 soak를 수행한다. 트래픽이 대표성을 갖지 못하면 synthetic load를 보완한다.

다음을 통과하면 종료한다.

- OOM과 process restart 0건
- heap·RSS가 지속적으로 우상향하지 않고 부하 감소 후 회수됨
- JFR/GC 기록에서 장시간 stop-the-world, allocation 폭증 또는 thread pinning이 허용 기준을
  넘지 않음
- DB connection pool 고갈과 처리되지 않은 request 누적이 없음
- outbox backlog와 WebSocket publish lag가 정상 범위로 회복됨
- 사전 등록한 오류율과 p95/p99 latency budget 충족

JFR, GC log, proxy·application metric, outbox·pub/sub 지표와 실행 명령은 원본 artifact로 보존한다.

### 6. rollback·recovery 리허설과 전체 cutover

전체 전환 전에 canary 상태에서 다음 장애를 실제로 주입하거나 동등한 통제 실험으로 검증한다.

- Spring health 실패와 proxy의 FastAPI rollback
- OpenAI 429·timeout 증가
- outbox publisher 중단과 재시작
- pub/sub 또는 FastAPI consumer 중단과 backlog replay
- Spring 재시작 및 진행 중 요청의 idempotent retry

rollback 후 legacy API와 WebSocket smoke가 성공하고, 이미 commit된 Spring outbox event의 처리
방향이 명확하며, 데이터 수동 수정 없이 서비스가 회복되어야 한다. 이 리허설과 1~6시간 soak를
통과한 뒤에만 대상 HTTP route를 100% Spring으로 전환한다.

전체 cutover 뒤에도 사전 등록한 관찰 시간 동안 rollback switch와 FastAPI 용량을 유지한다.
관찰 기간 종료, 미해결 데이터 불일치 0건, outbox backlog 정상화 및 운영 증거 링크가 모두
확인되어야 production 전환 완료로 기록한다.

## 배포 상태 정의

- **코드 완료**: Spring 구현, 테스트와 CI가 통과했지만 live route는 FastAPI가 소유한다.
- **Canary**: 일부 안정적인 ownership 단위만 Spring이 처리하며 즉시 rollback할 수 있다.
- **Cutover**: 대상 route의 100%를 Spring이 처리하지만 사후 관찰과 rollback window가 남아 있다.
- **Production 완료**: soak, recovery 리허설, 전체 cutover와 사후 관찰 gate가 모두 통과했다.

ADR이 Accepted가 되는 것과 Production 완료는 별도 상태다. 이 ADR의 채택만으로 운영 전환이
완료되었다고 표현하지 않는다.

## 결과 기록과 변경 관리

운영 전환 Issue 하나를 상위 추적 단위로 만들고 각 단계의 담당자, 수치 기준, 실행 결과와 증거
링크를 기록한다. 코드·설정 변경은 OpenAI 계약, outbox/pub-sub bridge, proxy·관측성 및 runbook 등
독립적으로 rollback 가능한 PR로 나눈다.

실행 중 발견한 defect 수정은 PR과 테스트로 남기되, 이 ADR의 ownership 및 단계적 전환 원칙을
변경해야 한다면 별도 후속 ADR로 대체한다. pub/sub 제품과 구체 SLO처럼 아직 확정되지 않은 항목은
Issue에서 사전 등록하고, 장기 architecture 결정이 되면 별도 ADR로 승격한다.

## 결과와 영향

### 기대 효과

- 장애 원인을 단계별로 격리하고 production blast radius를 제한한다.
- 실제 OpenAI, JVM resource와 WebSocket event 전달을 mock benchmark와 분리해 입증한다.
- proxy rollback과 outbox recovery를 문서가 아니라 실행 증거로 확인한다.
- 코드 완료, canary, cutover와 production 완료를 혼동하지 않는다.

### 비용과 제약

- 일괄 전환보다 준비 기간과 운영 관찰 비용이 증가한다.
- 전환 기간에는 Spring과 FastAPI 양쪽의 배포 가능 상태와 schema 호환성을 유지해야 한다.
- 외부 pub/sub 운영, event deduplication, backlog monitoring과 recovery 책임이 추가된다.
- WebSocket 자체의 Spring 전환은 이 ADR 범위가 아니며 별도 검증과 후속 ADR이 필요하다.
