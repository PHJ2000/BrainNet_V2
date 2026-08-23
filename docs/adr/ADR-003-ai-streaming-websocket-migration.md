# ADR-003: AI·스트리밍·WebSocket의 Java 25 + Spring 전환 검증

- 상태: Accepted
- 사전 등록일: 2026-08-20
- 대상: BrainNet AI 생성, SSE 스트리밍, 프로젝트 WebSocket 브로드캐스트
- 선행 결정: ADR-002는 프로젝트·노드 트랜잭션 코어만 Spring으로 전환하고 이 영역은 FastAPI에 남겼다.

## 결정 질문

트랜잭션 코어에 이어 AI 호출과 실시간 연결도 Java 25 + Spring으로 전환하여 전체 백엔드 전환을
승인할 것인가, 아니면 해당 워크로드는 FastAPI에 유지할 것인가?

현재 BrainNet AI 경로는 `async def` 안에서 동기 OpenAI SDK를 호출한다. WebSocket은 프로세스
메모리의 project별 연결 집합을 순회하여 투표 이벤트를 전송한다. 실제 OpenAI 비용과 응답 변동을
판정에서 분리하기 위해 제어 가능한 HTTP mock provider를 사용하되, 실제 TCP 연결, 지연, chunked
SSE, upstream 오류와 연결 중단을 포함한다.

## 선택지

1. 전체 전환: AI·SSE·WebSocket까지 Spring으로 이동한다.
2. 하이브리드 유지: 트랜잭션 코어는 Spring, AI·실시간 연결은 교정된 FastAPI에 둔다.
3. 전환 보류: 현재 FastAPI 구현을 유지하고 blocking AI 호출 등 확인된 위험만 먼저 수정한다.

## 사전 등록된 비교군

| ID | 구현 | 역할 |
|---|---|---|
| FL | 현재 의미를 재현한 FastAPI | async event loop 안의 blocking AI 호출 기준선 |
| FS | async HTTP client와 연결 정리를 적용한 FastAPI | 공정 비교군 |
| J | Java 25, Spring MVC, virtual thread, Spring WebSocket | 전체 전환 후보 |

FL은 AI generate에만 포함한다. SSE와 WebSocket의 전환 판단은 정상적인 비동기 구현인 FS와 J를
비교한다. 결과를 Python 또는 Java 언어 자체의 보편적 우위로 일반화하지 않는다.

## 고정 자원과 계약

- 애플리케이션별 2 CPU, 1 GiB, Spring `-Xms128m -Xmx512m`
- 동일 mock provider와 동일 네트워크, payload, 지연 및 timeout
- AI generate: 200 ms upstream 지연 후 JSON 응답
- SSE: 100 ms 후 첫 event, 이후 50 ms 간격으로 총 10 event
- WebSocket: project room 연결, client message echo, HTTP broadcast를 room의 모든 client가 수신
- 모든 부하 결과는 warm-up 후 3회 반복 중앙값 사용
- CPU peak, RSS peak, 오류율, 처리량, p50/p95/p99를 원본과 함께 저장

## 실험과 사전 판정 기준

### A. AI generate

- 동시성 10, 100, 300에서 각각 20초 측정
- FS와 J 모두 오류율 1% 미만이어야 한다.
- 300 동시성에서 J p95가 FS보다 20% 넘게 악화되면 전체 전환을 기각한다.
- FL의 event-loop blocking 영향은 현재 구현 위험의 증거로만 사용한다.

### B. SSE 스트리밍

- 동시 stream 20, 100, 각 client가 event 10개를 정확히 수신
- 연결 성공률과 완전 수신률 99% 이상
- J의 first-event p95가 FS보다 20% 넘게 악화되지 않아야 한다.
- client 중도 종료 후 upstream 활성 연결이 회수되어야 한다.

### C. WebSocket

- 동시 연결 100, 500에서 연결 성공률 99% 이상
- 각 연결의 echo와 room broadcast 전달 정확도 99% 이상
- J의 echo p95가 FS보다 20% 넘게 악화되지 않아야 한다.
- client disconnect 후 서버 connection count가 0으로 회수되어야 한다.

### D. 장애·취소·회복

- upstream HTTP 503은 두 구현 모두 stable 502 응답으로 변환한다.
- upstream timeout은 504로 변환하고 이후 정상 요청이 성공한다.
- SSE 중도 종료 후 누수 없이 새 stream이 성공한다.
- WebSocket 재연결과 서버 재시작 후 신규 연결이 성공한다.

### E. soak와 운영성

- FS와 J를 각각 15분 동안 AI 50 concurrency, SSE 20 connection, WebSocket 100 connection 혼합 부하로 실행한다.
- 오류율 1% 미만, OOM·재시작 0, 종료 시 활성 연결 0이어야 한다.
- 마지막 5분 RSS 중앙값이 첫 5분보다 20% 넘게 증가하면 메모리 안정성 게이트 실패다.
- 15분 통과는 운영 장기 안정성의 완전한 증명이 아니며, 운영 전 1~6시간 검증을 후속 gate로 둔다.

### F. endpoint routing과 rollback

- proxy에서 `/ai`, `/projects/*/ws`를 Spring으로 전환한 뒤 FastAPI로 되돌린다.
- 두 방향에서 AI, SSE, WebSocket smoke가 성공해야 한다.
- 기존 WebSocket 연결의 무중단 이전은 보장하지 않으며 client 재연결 계약을 확인한다.

## 결정 규칙

선택지 1은 FS 대비 J가 A~F의 모든 핵심 gate를 통과할 때만 채택한다. 성능이 비슷해도 전체 단일
스택의 변경 안전성과 운영 단순화가 이점이 될 수 있다. 핵심 gate가 실패하거나 자원 비용이 현저히
증가하면 선택지 2를 유지한다. FL만 이기고 FS에 열등한 결과는 Java 전환 근거로 사용하지 않는다.

## 결과 기록 위치

- 구현과 실행기: `experiments/realtime-ai/`
- 원시 결과: `experiments/realtime-ai/results/raw/`
- 최종 보고서: `experiments/realtime-ai/results/final-report.md`

결과 확인 후 이 문서의 상태, 실제 결과, 판정과 결정만 갱신한다. 위 기준은 변경하지 않는다.

## 실제 결과

2026-08-20 WSL2 단일 호스트에서 애플리케이션별 2 CPU/1 GiB로 실행했다. 본 결과는 warm-up 후
3회 중앙값이다.

| workload | 부하 | FastAPI safe | Spring | 판정 |
|---|---:|---:|---:|---|
| AI generate | 300 concurrency | 53.57 RPS, p95 6,027 ms, 실패 77.55% | 557.00 RPS, p95 765 ms, 실패 0% | Spring 통과 |
| SSE first event | 100 streams | p95 699 ms, 완전 수신 100% | p95 265 ms, 완전 수신 100% | Spring 통과 |
| WebSocket echo | 500 connections | p95 58.42 ms, broadcast 100% | p95 152.46 ms, broadcast 100% | **Spring 비열등성 실패** |

현재 blocking 의미의 FastAPI legacy는 10 concurrency에서도 4.81 RPS, p95 2.1초였으며
100/300 concurrency에서 실패율이 93% 이상이었다. 이는 현재 AI handler의 동기 OpenAI 호출을
전환과 무관하게 교정해야 한다는 근거다.

provider 503·timeout·회복, SSE 취소, WebSocket disconnect·재연결은 FS와 J가 모두 통과했다.
proxy의 Spring cutover와 FastAPI rollback 뒤 AI·SSE·WebSocket 신규 연결도 모두 통과했다.

15분 혼합 soak에서 FS는 실패율 0.177%, RSS 67.2→67.2 MiB, 재시작/OOM 0이었다. J는 실패율
0%, RSS 634.3→635.0 MiB, 재시작/OOM 0이었다. 두 구현 모두 안정성 gate를 통과했으나 Spring
RSS는 FS의 9.45배였다.

사후 FastAPI 2-worker 민감도에서는 AI 처리량이 개선됐지만 process-local WebSocket room이
worker마다 분리되어 broadcast 수신률 중앙값이 100 연결 75%, 500 연결 80%로 떨어졌다. 외부
pub/sub 없이 worker 수만 늘리는 방식은 올바른 대안이 아니다.

## 판정

| Gate | 결과 |
|---|---|
| AI 오류율·p95 | 통과 |
| SSE 완전 수신·first-event | 통과 |
| WebSocket 정확성 | 통과 |
| WebSocket p95 비열등 | **실패, 500 연결에서 FS보다 161% 악화** |
| 장애·취소·회복 | 통과 |
| 15분 soak | 통과 |
| routing·rollback | 통과 |

## 결정

선택지 2인 하이브리드를 유지한다. ADR-002에 따라 프로젝트·노드 트랜잭션 코어의 Spring 전환은
계속하지만, AI·SSE·WebSocket까지 포함한 전체 즉시 Java 전환은 승인하지 않는다.

Spring AI·SSE 후보의 결과는 강하지만 사전 결정 규칙은 A~F 모든 핵심 gate 통과를 요구했다.
제품의 절대 WebSocket SLO 없이 실험 후 상대 기준을 완화하지 않는다. AI·SSE·WebSocket ownership은
이번 ADR로 이동하지 않으며, 별도 범위 결정이나 개선된 Spring WebSocket 후보의 재검증이 필요하다.

현재 FastAPI AI handler의 blocking OpenAI 호출은 전환 여부와 무관하게 async client 또는 제한된
thread offload로 교정한다. multi-worker/instance WebSocket을 운영하려면 어느 언어든 외부 pub/sub와
client reconnect/resubscribe 계약을 도입해야 한다.

전체 원시 결과, 민감도, 보정 이력과 한계는 `experiments/realtime-ai/results/final-report.md`에 기록한다.
