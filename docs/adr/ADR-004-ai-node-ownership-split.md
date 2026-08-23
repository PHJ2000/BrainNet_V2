# ADR-004: AI 노드 생성과 WebSocket의 소유권 분리

- 상태: Accepted
- 사전 등록일: 2026-08-20
- 대상: `POST /projects/{project_id}/nodes`의 AI 생성 분기와 프로젝트 WebSocket
- 선행 결정: ADR-002는 프로젝트·노드 트랜잭션 코어의 Spring 전환을 채택했고, ADR-003은 WebSocket 비열등성 실패 때문에 AI·SSE·WebSocket 묶음 전환을 기각했다.

## 결정 질문

AI, SSE, WebSocket을 하나의 실시간 범위로 계속 묶을 것인가, 아니면 실제 제품 경계에 맞춰 AI 노드
생성은 Spring 노드 코어에 포함하고 WebSocket만 FastAPI에 유지할 것인가?

## 현재 제품에서 확인한 경계

1. 현재 제품에는 SSE endpoint와 `EventSource`/stream 소비 코드가 없다. ADR-003의 SSE 결과는 미래
   기능 후보의 근거일 뿐 현재 ownership 전환 대상이 아니다.
2. AI는 별도 `/ai` endpoint가 아니다. `POST /projects/{project_id}/nodes` 요청의 `ai_prompt` 분기에서
   provider를 호출하고 같은 요청 안에서 GHOST node를 저장한다.
3. 일반 node 생성도 같은 method/path를 사용한다. proxy가 request body의 `ai_prompt` 유무로 FastAPI와
   Spring을 나누면 계약과 write ownership이 불필요하게 복잡해진다.
4. 프로젝트 WebSocket은 `/projects/{project_id}/ws`라는 독립 protocol 경계다. vote write와 socket
   fan-out을 분리하려면 Spring write 이후 FastAPI socket service로 event를 전달하는 outbox/pub-sub
   경계가 필요하다.

## 선택지

1. AI node 분기와 WebSocket을 모두 FastAPI에 유지한다.
2. `POST /projects/{project_id}/nodes` 전체와 AI node 생성을 Spring이 소유하고 WebSocket만 FastAPI에
   한시적으로 유지한다.
3. WebSocket까지 즉시 Spring으로 전환한다.

## 추가 실험

ADR-003의 분리된 provider benchmark만으로는 provider 성공 후 DB 저장 계약을 입증하지 못했다.
따라서 `experiments/ownership-split/`에서 다음을 같은 mock provider와 PostgreSQL로 검증한다.

- FS: shared async HTTP client와 async SQLAlchemy를 사용하는 corrected FastAPI 2 workers
- J: Java 25, Spring MVC virtual thread, JDK HTTP client, JDBC transaction
- 동일 `POST /projects/{project_id}/nodes`, request/response JSON, provider 200 ms, pool 총 30
- 10/100/300 concurrency, 10초 측정, 3회 반복의 중앙값
- provider 503과 timeout에서 502/504를 반환하고 node row를 남기지 않는지 검사
- 성공 응답이 기존 frontend가 기대하는 `[NodeOut]` 배열과 GHOST node 필드를 보존하는지 검사

## 사전 판정 기준

선택지 2는 다음을 모두 만족할 때 채택한다.

1. 현재 repository에 운영 SSE 생산자·소비자가 없다는 정적 검사가 통과한다.
2. J의 성공 응답 계약 검사가 100% 통과한다.
3. J가 provider 503/timeout/recovery 상태 계약을 지키고 실패 시 DB write를 0건 남긴다.
4. J의 300 concurrency 실패율이 1% 미만이고 FS 대비 p95가 20% 넘게 악화되지 않는다.
5. 1 GiB 제한에서 J의 OOM·재시작·pool timeout이 없다.
6. `POST /projects/{project_id}/nodes`의 일반/AI request 변형 전체를 Spring으로
   cutover/legacy rollback하고 WebSocket 경로는 FastAPI로 유지할 수 있다.
7. node table write owner는 cutover 시점에 하나뿐이며 request-body 기반 분기 routing을 사용하지 않는다.

J의 RSS가 FS의 4배를 넘으면 비용 위험으로 기록하되 1 GiB 안정성 gate와 분리한다. 실제 OpenAI TLS,
SDK 응답 parsing, rate limit과 비용은 mock이 증명하지 못하므로 운영 전 staging contract test와 소규모
canary를 별도 배포 gate로 둔다.

선택지 3은 ADR-003 WebSocket p95 비열등성 실패 때문에 이번 결정에서 채택하지 않는다. WebSocket
후보는 WebFlux/Netty와 외부 pub/sub를 포함한 별도 재검증이 필요하다.

## 결과 기록 위치

- 구현과 실행기: `experiments/ownership-split/`
- 원시 결과: `experiments/ownership-split/results/raw/`
- 최종 보고서: `experiments/ownership-split/results/final-report.md`

결과 확인 후 이 문서의 상태, 실제 결과, 판정과 결정만 갱신한다. 위 기준은 변경하지 않는다.

## 실제 결과

2026-08-20에 동일 WSL2 호스트, PostgreSQL 15.13, 애플리케이션별 2 CPU/1 GiB, DB pool 총
30 조건에서 실행했다. provider는 모든 성공 요청에 200 ms 지연을 적용했다. 각 결과는 10초 측정
3회의 중앙값이며 provider 호출, JSON parsing, GHOST node INSERT와 응답 직렬화를 모두 포함한다.

| concurrency | 구현 | RPS | p95 | 오류율 |
|---:|---|---:|---:|---:|
| 10 | corrected FastAPI | 38.49 | 275.59 ms | 0% |
| 10 | Java 25 + Spring | 47.83 | 220.71 ms | 0% |
| 100 | corrected FastAPI | 128.55 | 1,385.21 ms | 0% |
| 100 | Java 25 + Spring | 419.89 | 304.90 ms | 0% |
| 300 | corrected FastAPI | 161.12 | 4,060.74 ms | 1.6% |
| 300 | Java 25 + Spring | 550.47 | 881.59 ms | 0% |

300 concurrency에서 Spring은 FS보다 RPS가 241.7% 높고 p95가 78.3% 낮았다. Spring은 오류가
없었고 FS는 DB pool timeout을 포함해 중앙 오류율 1.6%였다. 이 결과는 Java 언어 하나가 아니라
Java 25 virtual thread, Spring MVC, JDK HTTP client와 JDBC로 구성한 후보 스택 전체의 결과다.

두 축소 구현 모두 AI 생성에서 기존 frontend가 소비하는 `[NodeOut]` 배열, GHOST 상태,
위치·depth·order·parent와 빈 tags 계약을 통과했다. provider 503은 502, 1초 초과는 504로
변환했고 두 실패 뒤 실험 DB node 수는 0이었다. 이후 정상 요청은 201과 node 1건으로 회복했다.
이 harness는 실제 BrainNet 인증·멤버십·tag 상속과 node GET/PATCH/DELETE/activate/deactivate를
구현하지 않으므로 운영 node API 전체 계약을 증명하지 않는다.

300 concurrency warm load 직후 RSS는 FS 168.7 MiB, J 317.7 MiB로 J가 1.88배였으며 양쪽 모두
재시작과 OOM은 0이었다. ADR-003의 다른 혼합 workload에서는 Spring RSS가 더 크게 관찰됐으므로
이 수치를 일반적인 메모리 비율로 보지 않는다.

repository 정적 검사에서 backend SSE 생산자와 frontend SSE 소비자는 모두 0건이었다. nginx에서
`POST /projects/{id}/nodes` 경로를 Spring으로 전환하고 `/projects/{id}/ws`만 FastAPI로 고정한
smoke가 통과했다. POST 경로를 FastAPI로 rollback한 뒤에도 축소 node 생성 계약과 FastAPI
WebSocket echo가 통과했다.

## 판정

| 게이트 | 결과 |
|---|---|
| 현재 SSE 생산자·소비자 없음 | 통과, 각 0건 |
| Spring 성공 응답 계약 | 통과 |
| provider 장애·timeout·회복 및 DB 무기록 | 통과 |
| Spring 300 concurrency 오류율 1% 미만 | 통과, 0% |
| FS 대비 Spring p95 악화 20% 이내 | 통과, 78.3% 감소 |
| 1 GiB에서 OOM·재시작 없음 | 통과 |
| node POST 경로 Spring cutover | 통과 |
| node POST 경로 FastAPI rollback | 통과 |
| WebSocket FastAPI 고정 | 통과 |

## 결정

선택지 2를 채택한다. `POST /projects/{project_id}/nodes`의 일반 생성과 `ai_prompt` 생성은 나누지
않고 Spring node core가 함께 소유한다. 현재 존재하지 않는 SSE는 전환 범위에서 제외한다.
`/projects/{project_id}/ws`는 ADR-003에서 더 나은 결과를 낸 FastAPI에 한시적으로 유지한다.

운영 구조는 Spring의 DB commit 이후 outbox event를 발행하고 FastAPI WebSocket service가 외부
pub/sub에서 소비하는 방향으로 제한한다. Spring이 FastAPI의 process-local socket set을 직접
호출하거나 두 backend가 같은 node/vote write를 함께 소유하지 않는다.

운영 cutover 전에는 실제 OpenAI staging에서 SDK 응답 parsing, TLS, 429·timeout·취소 계약을
검사하고 `Idempotency-Key` 또는 동등한 중복 node 방지 계약을 추가한다. shadow contract test,
소규모 canary, 1~6시간 soak, Spring `-Xmx512m`/JFR 확인 후 전체 node path를 전환한다. 이 배포
gate를 통과하지 않았으므로 이번 결정은 production 전환 완료를 뜻하지 않는다.

WebSocket FastAPI 예외는 영구 결정이 아니다. 실제 제품 연결 수의 절대 latency SLO를 정한 뒤
WebFlux/Netty와 Redis 등 외부 pub/sub 후보를 재측정하는 후속 ADR에서 제거 여부를 결정한다.
