# ADR-001: Java 25 + Spring 백엔드로의 단계적 전환

- 상태: Accepted
- 작성일: 2026-08-20
- 대상: BrainNet 백엔드

## 맥락

BrainNet의 현재 백엔드는 Python/FastAPI, SQLAlchemy asyncio, asyncpg로 구현되어 있다.
향후 다중 사용자 편집, WebSocket fan-out, 동일 프로젝트에 대한 동시 쓰기와 외부 AI API
호출이 늘어날 경우 처리량뿐 아니라 코드의 이해 가능성, 데이터 정합성, 장애 진단 가능성이
중요해진다.

현재 AI 노드 생성 경로는 `async def` 안에서 동기 OpenAI SDK를 호출한다. 현재 배포 명령은
Uvicorn worker 하나를 실행한다. 이 조합에서는 외부 API를 기다리는 동안 event loop가 막힐 수
있다. 반면 Java 가상 스레드는 blocking thread-per-request 코드를 유지하면서 I/O 대기 중
carrier thread를 반환할 수 있다.

다만 다음 사실을 구분한다.

1. 가상 스레드는 Java 21에서 정식 도입되었으며 Java 25만의 기능이 아니다.
2. 가상 스레드는 CPU 연산이나 단일 요청을 더 빠르게 만드는 기능이 아니라 높은 I/O 동시성에서
   처리량을 높이기 위한 기능이다.
3. FastAPI asyncio도 올바르게 작성된 비동기 I/O에서는 높은 동시성을 처리할 수 있다.
4. 중복 생성, lost update 같은 데이터 정합성은 언어가 아니라 DB constraint, transaction,
   isolation, optimistic/pessimistic lock 설계로 해결해야 한다.
5. Java 25의 Structured Concurrency는 preview이므로 본 결정의 필수 근거로 사용하지 않는다.

## 결정 질문

BrainNet의 트랜잭션 중심 백엔드를 Java 25 + Spring으로 단계적으로 전환할 것인가?

## 선택지

1. FastAPI를 유지하고 blocking 호출, worker 구성, WebSocket 공유 상태를 개선한다.
2. 모든 백엔드를 Java 25 + Spring으로 단계적으로 전환한다.
3. 프로젝트·노드·투표·협업 코어는 Spring으로 전환하고 AI 기능은 Python 서비스로 유지한다.

## 결정 동인

- 목표 부하에서의 p95/p99 latency와 오류율
- 동일 자원에서의 지속 가능한 처리량
- CPU와 최대 메모리 사용량
- 동시 쓰기 시 도메인 invariant 보존
- blocking I/O가 포함된 코드의 구현 및 장애 진단 난이도
- 단계적 배포와 즉시 rollback 가능성
- Python AI 생태계를 유지할 가치

## 사전 등록된 실험

### 비교군

| ID | 구현 | 목적 |
|---|---|---|
| F0 | FastAPI, async handler 안에서 blocking 대기 | 현재 AI 호출 구조를 재현 |
| F1 | FastAPI, 올바른 async 대기 | 수정 가능한 FastAPI와 공정 비교 |
| J0 | Java 25 + Spring MVC, platform thread | 가상 스레드 효과 분리 |
| J1 | Java 25 + Spring MVC, virtual thread | 전환 후보 |

### 고정 조건

- 동일 호스트와 Docker 네트워크
- 애플리케이션별 CPU 2개, 메모리 1 GiB 제한
- PostgreSQL 한 인스턴스와 동일 schema
- 애플리케이션별 DB connection pool 최대 30
- 네 비교 서비스의 pool 합계가 DB 자체 상한에 걸리지 않도록 PostgreSQL `max_connections=200`
- 응답 body와 endpoint contract 동일
- 외부 서비스는 고정된 지연으로 모사하여 인터넷 변동 제거
- 각 주요 케이스 60초 warm-up 후 180초 측정이 목표이며, 자원 또는 시간 제약 시 최소
  15초 warm-up, 30초 측정, 3회 반복을 하한으로 한다.
- 결과가 경계값 근처이면 긴 측정을 추가한다.

### 워크로드

1. `GET /io?delay_ms=200`: 외부 AI API의 200 ms I/O 대기를 모사한다.
2. `GET /db?delay_ms=50`: connection pool을 거쳐 PostgreSQL I/O 대기를 수행한다.
3. `POST /roots/{project_id}`: 같은 project에 100개 요청을 동시에 보내 root가 정확히 하나만
   생성되는지 확인한다.

I/O와 DB 테스트는 10, 100, 500 동시 사용자를 기본 단계로 실행한다. 필요하면 1,000까지
올린다.

### 수집 지표

- 성공 RPS
- p50, p95, p99 latency
- HTTP 오류율과 timeout
- 컨테이너 CPU와 최대 메모리
- DB connection 수와 pool timeout
- root 생성 성공 수 및 최종 DB row 수
- JVM GC/가상 스레드 관련 경고와 FastAPI event-loop stall 징후

## 사전 판정 규칙

1. 정합성 invariant 위반이 있는 구현은 성능과 무관하게 채택하지 않는다.
2. 목표 단계에서 HTTP 오류율은 1% 미만이어야 한다.
3. Java가 더 빠르다는 결론은 F1 대비 J1이 동일 오류율 조건에서 다음 중 하나 이상을 반복
   측정에서 만족할 때만 내린다.
   - 지속 가능한 처리량 20% 이상 증가
   - 동일 부하 p95 latency 20% 이상 감소
   - 동일 부하 CPU 사용량 20% 이상 감소
4. J1이 F0보다 우수하지만 F1과 의미 있는 차이가 없다면, 이는 Java 우위가 아니라 현재
   FastAPI의 blocking 구현 결함으로 판정한다.
5. J1이 J0보다 개선되면 그 차이만 Java 가상 스레드 효과로 판정한다.
6. 성능 차이가 작으면 성능을 마이그레이션 근거로 사용하지 않고 유지보수성, 타입 안정성,
   운영 복잡성과 팀 역량으로 결정한다.

## 단계적 전환 제약

- 실험 branch와 실제 migration branch를 분리한다.
- `backend-legacy`와 `backend-spring`을 일정 기간 함께 운영한다.
- reverse proxy에서 endpoint 단위로 라우팅하고 즉시 legacy로 되돌릴 수 있어야 한다.
- 하나의 테이블/aggregate에 대한 쓰기 소유자는 한 시점에 한 백엔드만 가진다.
- schema 변경은 expand/contract 방식으로 수행한다.
- API contract test를 통과한 endpoint만 Spring으로 전환한다.

## 결정

선택지 1을 채택한다. 현재는 FastAPI를 유지하고 blocking I/O와 데이터 정합성 문제를 먼저
수정한다. “Java 25가 FastAPI보다 동시성을 더 잘 처리한다”는 주장을 전체 마이그레이션 근거로
사용하지 않는다.

500 VU, 200 ms I/O에서 corrected FastAPI는 2,666.47 RPS / p95 210.73 ms,
Spring virtual은 2,637.96 RPS / p95 216.01 ms로 사실상 동급이었다. 반면 현재 blocking
FastAPI는 52.04 RPS / p95 약 10초 / 오류율 90.43%였다. 이는 Java 우위가 아니라 현재
blocking OpenAI 호출의 event-loop 차단임을 보여준다.

Spring virtual은 같은 Spring platform 대비 I/O 500 VU에서 RPS가 168.1% 높고 p95가
61.6% 낮아 가상 스레드의 효과 자체는 확인했다. 그러나 DB pool 30 경로에서는 Spring
platform이 virtual보다 p95가 낮았고, Spring virtual의 peak RSS는 고부하에서 크게 증가했다.

정합성 실험은 모든 구현에서 100개 동시 요청당 201 한 개, 409 아흔아홉 개, 최종 row 한 개로
동일했다. 이 결과는 PostgreSQL primary key와 atomic insert가 만든 것이므로 언어 선택과
분리한다.

전체 결과와 폐기/재실험 근거는 `experiments/concurrency/results/final-report.md`에 기록한다.

## 결과에 따른 후속 조치

1. FastAPI OpenAI 호출을 진짜 async client로 교체한다.
2. root uniqueness를 DB constraint로 강제하고 node update의 충돌 정책을 정의한다.
3. WebSocket 상태를 외부화하기 전에는 worker 수 증가를 성능 해결책으로 사용하지 않는다.
4. Java 전환을 학습, 타입 안정성, 트랜잭션 모델 또는 운영성 때문에 추진하려면 별도 ADR을
   작성하고 실제 vertical slice로 다시 검증한다.
5. 향후 재평가 시 Spring virtual의 JFR/GC/heap 실험과 WebSocket fan-out을 포함한다.

## 근거 자료

- OpenJDK JEP 444, Virtual Threads: https://openjdk.org/jeps/444
- OpenJDK JEP 491, Synchronize Virtual Threads without Pinning: https://openjdk.org/jeps/491
- OpenJDK JEP 505, Structured Concurrency (Fifth Preview): https://openjdk.org/jeps/505
- Spring Boot Virtual Threads: https://docs.spring.io/spring-boot/reference/features/spring-application.html
- FastAPI Concurrency and async/await: https://fastapi.tiangolo.com/async/
- Python 3.11 Coroutines and Tasks: https://docs.python.org/3.11/library/asyncio-task.html
- PostgreSQL Transaction Isolation: https://www.postgresql.org/docs/current/transaction-iso.html
- Grafana k6 API load testing: https://grafana.com/docs/k6/latest/testing-guides/api-load-testing/
