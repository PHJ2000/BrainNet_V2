# ADR-002: 트랜잭션 코어를 Java 25 + Spring으로 단계적 전환

- 상태: Accepted
- 사전 등록일: 2026-08-20
- 대상: BrainNet 프로젝트·노드 트랜잭션 코어
- 선행 결정: ADR-001은 Java의 보편적인 동시성 성능 우위를 입증하지 못했다.

## 결정 질문

BrainNet의 프로젝트·노드 트랜잭션 코어를 Java 25 + Spring으로 endpoint 단위 전환할 것인가?

이번 결정은 Java가 FastAPI보다 무조건 빠르다는 가정에 의존하지 않는다. 실제 BrainNet 계약과
DB invariant를 사용하는 vertical slice에서 성능 비열등성, 변경 안전성, 동시성 정합성,
장애 진단성과 운영 비용을 함께 측정한다.

## 현재 기준선에서 확인한 위험

1. root node 생성은 기존 root를 `SELECT`한 뒤 별도 `INSERT`하므로 동시 요청 사이에 경쟁 구간이 있다.
2. node PATCH는 읽은 row를 조건 없는 `UPDATE`로 저장하며 version 계약이 없어 lost update를 알리지 못한다.
3. Python 모델과 소비 코드 사이의 필드 참조는 현재 빌드에 정적 타입 검사 단계가 없다.
4. 구조화된 오류 envelope와 요청 trace ID 계약이 없다.

이 문제들은 Python 자체의 한계가 아니므로 corrected FastAPI 비교군을 반드시 포함한다.

## 선택지

1. FastAPI를 유지하고 정합성·타입 검사·관측성을 보완한다.
2. 프로젝트·노드 트랜잭션 코어부터 Spring으로 단계적으로 전환하고 AI 기능은 당분간 FastAPI에 유지한다.
3. 전체 백엔드를 즉시 Spring으로 재작성한다.

## 사전 등록된 비교군

| ID | 구현 | 역할 |
|---|---|---|
| FL | 현재 FastAPI 의미를 재현한 legacy slice | 현재 위험의 기준선 |
| FS | DB constraint, optimistic version, trace를 적용한 FastAPI | 언어가 아닌 설계 개선 효과 분리 |
| J | 같은 DB·HTTP 계약을 구현한 Java 25 + Spring virtual thread | 전환 후보 |

## 고정 계약과 데이터 모델

- `POST /projects`: project, OWNER membership, ACTIVE root를 한 transaction에서 생성
- `POST /projects/{project_id}/nodes`: root node 동시 생성 계약
- `GET /projects/{project_id}/nodes/{node_id}`: node와 `version` 반환
- `PATCH /projects/{project_id}/nodes/{node_id}`: 요청 `expected_version`과 일치할 때만 수정
- 성공 PATCH는 version을 정확히 1 증가
- 충돌은 HTTP 409, validation은 422, 없음은 404
- 모든 응답은 `X-Trace-Id`, 모든 오류는 `code`, `message`, `trace_id` 포함
- 같은 PostgreSQL 15 schema, connection pool 30, 서비스별 2 CPU/1 GiB

FL은 현재 동작을 재현하기 위해 root DB uniqueness와 optimistic version 조건을 적용하지 않는다.
FS와 J는 같은 unique index와 atomic conditional update를 사용한다.

## 실험

### A. API·성능 비열등성

- 실제 JSON 직렬화, validation, DB transaction을 포함한다.
- read 80% + 충돌하지 않는 update 20% 혼합 workload
- 10, 100, 300 VU, 15초 warm-up, 30초 측정, 3회 반복
- RPS, p95/p99, HTTP 실패, CPU peak, RSS peak, DB connection 수 수집

### B. 동시성 정합성

1. root가 없는 같은 project에 root 생성 요청 100개를 동시에 보내 root가 하나만 생기는지 확인한다.
2. 같은 node/version에 서로 다른 content PATCH 100개를 동시에 보낸다.
3. FS와 J는 성공 1개, 409 99개, version 정확히 +1이어야 한다.
4. FL은 현재 위험을 관찰하되 J 채택 판단의 공정 비교는 FS 대 J로 한다.

### C. 계약 변경 검출

동일한 `order_index` 응답 필드 rename mutation을 수행한다.

- 생산자 DTO의 필드를 변경하고 소비 코드는 이전 필드를 계속 참조한다.
- Python은 현재 저장소의 공식 build 단계(`py_compile`)와 runtime contract test를 각각 실행한다.
- Java는 Maven compile과 runtime contract test를 실행한다.
- 최초 실패 단계, 진단 메시지, 실행 시간을 원본으로 저장한다.
- 이는 현재 toolchain 비교이며 Python 언어 전체의 능력으로 일반화하지 않는다.

### D. 장애 진단 계약

- validation 오류, missing row, version conflict, 의도적 DB 오류를 각 구현에 발생시킨다.
- 상태 코드, 오류 code, 응답 trace ID, 같은 trace ID의 구조화 로그 존재 여부를 자동 검사한다.
- 사람이 원인을 찾는 시간을 주관적으로 재지 않고 기계 검증 가능한 진단 필드를 사용한다.

## 사전 판정 기준

선택지 2를 채택하려면 J가 모두 충족해야 한다.

1. 정합성 invariant 위반 0건
2. 목표 부하의 HTTP 실패율 1% 미만
3. FS 대비 300 VU p95가 20% 넘게 악화되지 않음
4. 1 GiB 제한에서 OOM, 재시작, pool timeout 없음
5. 계약 mutation이 runtime 전 build/compile 단계에서 검출됨
6. 네 장애 유형 모두 status, stable code, trace ID, 대응 로그가 일치함
7. endpoint 단위 routing과 legacy rollback이 가능한 독립 서비스로 패키징됨

다음은 보조 판정이다.

- J가 FS 대비 RPS 또는 p95에서 20% 이상 개선하면 성능 이점으로 기록한다.
- J의 RSS가 FS의 4배를 넘으면 운영 비용 위험으로 기록하고 heap 제한 후 재실험한다.
- FS도 모든 핵심 이점을 같은 비용으로 달성하면 Java의 근거를 언어 우위가 아니라 팀 표준화와
  장기 변경 안전성으로 제한한다.

선택지 3인 전체 즉시 재작성은 이번 단일 slice가 성공해도 채택하지 않는다. AI 기능과 WebSocket은
별도 검증 없이는 전환 범위에 포함하지 않는다.

## 결과 기록 위치

- 구현과 실행기: `experiments/vertical-slice/`
- 원시 결과: `experiments/vertical-slice/results/raw/`
- 최종 보고서: `experiments/vertical-slice/results/final-report.md`

결과 확인 후 이 문서의 상태와 결정 절만 갱신한다. 사전 판정 기준은 변경하지 않는다.

## 실제 결과

2026-08-20에 같은 WSL2 호스트, PostgreSQL 15.13, 애플리케이션별 2 CPU/1 GiB,
애플리케이션별 총 DB pool 30 조건에서 실행했다. 부하 결과는 15초 warm-up과 30초 측정
3회의 중앙값이다. workload는 실제 JSON validation, 80% node GET, 20% version 조건부 PATCH와
DB transaction을 포함한다.

| VUs | 구현 | RPS | p95 | p99 | 오류율 | peak RSS |
|---:|---|---:|---:|---:|---:|---:|
| 10 | FastAPI safe | 452.27 | 49.08 ms | 62.46 ms | 0% | 132.4 MiB |
| 10 | Spring | 3,432.36 | 16.69 ms | 32.88 ms | 0% | 208.6 MiB |
| 100 | FastAPI safe | 481.12 | 489.74 ms | 744.48 ms | 0% | 140.9 MiB |
| 100 | Spring | 3,618.93 | 72.72 ms | 102.78 ms | 0% | 242.4 MiB |
| 300 | FastAPI safe | 454.29 | 2,220.47 ms | 3,982.72 ms | 0.51% | 155.3 MiB |
| 300 | Spring | 4,064.93 | 168.23 ms | 272.59 ms | 0% | 648.2 MiB |

300 VU에서 Spring은 FS보다 RPS가 794.8% 높고 p95가 92.4% 낮았다. 이는 이 vertical
slice에서 Java 25 + Spring MVC + JDBC + virtual thread 스택 전체가 FastAPI + SQLAlchemy
asyncio + asyncpg 스택보다 우수했다는 결과다. Java 언어나 virtual thread 하나만의 인과 효과로
분해하지 않는다.

현재 의미를 재현한 FL은 root 경쟁 3회에서 최종 root가 6, 18, 29개였고 version 경쟁에서는
100개 요청이 모두 성공하여 version이 100 증가했다. FS와 J는 모든 6개 경쟁 실험에서 각각
성공 1개, 409 99개, 최종 root 1개 또는 version +1을 만족했다. 이는 Java 자동 보장이 아니라
두 구현에 적용한 DB unique index와 atomic conditional update의 효과다.

계약 field rename mutation에서 현재 Python build인 `py_compile`은 성공하고 runtime probe가
실패했다. Java는 Maven test compilation에서 `cannot find symbol`로 runtime 전에 실패했다.
이는 현재 저장소 toolchain에서 Java의 compile-time 변경 검출 이점을 확인한 것이며,
Python에 mypy/pyright를 도입한 경우까지 일반화하지 않는다.

FS와 J 모두 validation, missing row, version conflict, DB failure에서 status, stable error code,
응답 trace ID, 같은 trace ID의 로그와 transaction rollback 검사를 통과했다. nginx proxy를
Spring으로 전환한 뒤 legacy FastAPI로 되돌리는 실제 routing 검사도 통과했다.

## 프로토콜 보정

사전 판정 기준은 바꾸지 않았고 다음 환경 오류만 보정했다. 모든 이전 원본은
`results/protocol-corrections/`에 보관한다.

1. FS single worker가 2 CPU 중 한 코어만 사용해 worker 2로 재실험했다.
2. worker마다 pool 30이 생성된 결과를 폐기하고 worker마다 15, 총 pool 30으로 재실험했다.
3. Spring default heap의 peak RSS가 919 MiB여서 사전 규칙대로 `-Xmx512m`로 재실험했다.
4. background FS pool 60이 PostgreSQL 전체 연결 표본에 포함된 Spring 결과를 보존하고,
   최종 pool 30 환경에서 Spring을 재실험했다.

최종 Spring RSS는 300 VU에서 648.2 MiB로 FS의 4.17배였다. 1 GiB 제한에서 OOM이나 재시작은
없었지만 메모리 비용은 남은 운영 위험이다.

## 판정

| 게이트 | 결과 |
|---|---|
| J invariant 위반 0건 | 통과 |
| 목표 부하 오류율 1% 미만 | 통과, 300 VU 0% |
| FS 대비 300 VU p95 악화 20% 이내 | 통과, 오히려 92.4% 감소 |
| 1 GiB에서 OOM·재시작·pool timeout 없음 | 통과 |
| 계약 변경 compile 단계 검출 | 통과 |
| 네 장애 유형의 code·trace·로그·rollback | 통과 |
| 독립 패키징·Spring 전환·legacy rollback | 통과 |

## 결정

선택지 2를 채택한다. 프로젝트·노드 트랜잭션 코어를 Java 25 + Spring으로 endpoint 단위
전환하고 AI 기능과 아직 검증하지 않은 WebSocket 기능은 FastAPI에 유지한다.

이 결정은 전체 즉시 재작성을 승인하지 않는다. 첫 운영 slice는 project/node read와 version
기반 PATCH로 제한하고, 한 테이블의 write owner는 전환 시점에 한 백엔드만 갖는다. schema는
expand/contract 방식으로 `version`과 active-root unique constraint를 먼저 추가한다. API contract
test, shadow read, canary, proxy cutover, legacy rollback 순서로 진행한다.

Spring 컨테이너는 `-Xmx512m`를 기본으로 두고 실제 데이터 soak와 JFR/GC 검사를 통과해야 한다.
인증, AI 호출, WebSocket fan-out은 각각 별도 ADR과 실험 없이는 전환 범위에 넣지 않는다.

전체 원시 결과, 보정 이력과 한계는 `experiments/vertical-slice/results/final-report.md`에 기록한다.
