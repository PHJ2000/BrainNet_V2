# ADR-004 최종 실험 보고서

## 결론

**AI node 생성은 Spring node core에 포함하고 WebSocket만 FastAPI에 유지한다. 현재 제품에 SSE는
없으므로 SSE migration은 결정 대상이 아니다.** 사전 등록한 9개 gate를 모두 통과했다.

## 실제 제품 경계

- AI는 별도 endpoint가 아니라 `POST /projects/{project_id}/nodes`의 `ai_prompt` 분기다.
- 일반 node와 AI node를 request body로 나눠 routing하면 같은 path와 table에 write owner가 둘이 된다.
- WebSocket은 `/projects/{project_id}/ws`라는 독립 protocol 경계다.
- backend/frontend 정적 검사에서 현재 SSE 생산자·소비자는 각각 0건이었다.

따라서 이 ADR이 다루는 가장 작은 일관된 cutover 단위는 AI 분기만이 아니라
**`POST /projects/{project_id}/nodes`의 모든 request 변형**이다.

## 통합 부하 결과

동일 PostgreSQL, mock provider 200 ms, 애플리케이션별 2 CPU/1 GiB, DB pool 총 30 조건이다.
provider 호출부터 GHOST node INSERT와 JSON 응답까지 포함한 10초 측정 3회의 중앙값이다.

| concurrency | 구현 | RPS | p95 | 오류율 |
|---:|---|---:|---:|---:|
| 10 | FastAPI safe | 38.49 | 275.59 ms | 0% |
| 10 | Spring | 47.83 | 220.71 ms | 0% |
| 100 | FastAPI safe | 128.55 | 1,385.21 ms | 0% |
| 100 | Spring | 419.89 | 304.90 ms | 0% |
| 300 | FastAPI safe | 161.12 | 4,060.74 ms | 1.6% |
| 300 | Spring | 550.47 | 881.59 ms | 0% |

300 concurrency에서 Spring은 처리량 +241.7%, p95 -78.3%였다. 결과는 Java 언어 단독 효과가
아니라 측정한 전체 구현 스택의 차이다.

## 계약·장애·운영 검사

- 양쪽 축소 구현 모두 AI 생성의 `[NodeOut]`, GHOST, content, parent, 위치, depth/order, tags
  계약을 통과했다.
- provider 503→502, timeout→504, 두 실패의 DB write 0건, 이후 201 회복을 통과했다.
- 300 concurrency warm load 직후 RSS는 FastAPI 168.7 MiB, Spring 317.7 MiB였다.
- 양쪽 OOM과 restart는 0이었다.
- node POST 경로의 Spring cutover와 FastAPI rollback이 성공했다.
- 두 routing 방향 모두 `/projects/{id}/ws`는 FastAPI에 연결됐다.

## 판정

`gate-verification.json`의 9개 자동 gate가 모두 `true`이며 결정 값은
`split-ai-node-to-spring-websocket-fastapi`다.

## 운영 전 남은 gate

이번 실험은 실제 OpenAI TLS, SDK parsing, 429/rate limit, token 비용을 재현하지 않는다. schema와
인증도 migration 실험용 최소 계약이며 운영 구현 그 자체가 아니다. 실제 BrainNet의 멤버십,
parent tag 상속, root invariant와 node GET/PATCH/DELETE/activate/deactivate도 검증하지 않았다.
실제 전환 전 다음이 필요하다.

1. 실제 OpenAI staging contract와 429·timeout·취소 검사
2. AI 요청 retry의 중복 node를 막는 idempotency 계약
3. shadow contract, canary, rollback rehearsal
4. 실제 데이터 1~6시간 soak와 `-Xmx512m`, JFR/GC 확인
5. Spring outbox → 외부 pub/sub → FastAPI WebSocket fan-out 구현

원시 결과는 `raw/`, 중앙값은 `measurements.csv`, 기계 판정은 `gate-verification.json`에 있다.
