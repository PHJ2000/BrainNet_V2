# ADR-003 final experiment report

## 결론

**AI·SSE·WebSocket을 포함한 전체 즉시 Java 전환은 채택하지 않는다. ADR-002의 하이브리드 결정을
유지한다.** Java 25 + Spring 후보는 AI generate와 SSE에서 크게 우수했고 15분 soak도 오류 없이
통과했지만, WebSocket 500 연결 echo p95가 교정 FastAPI보다 161% 높아 사전 등록한 20%
비열등성 gate를 실패했다. Spring의 soak RSS도 FastAPI의 9.45배였다.

이는 Spring 후보가 나쁘다는 결론이 아니다. 이번 후보 그대로 모든 endpoint를 한 번에 넘길 근거가
충분하지 않다는 결론이다. 프로젝트·노드 트랜잭션 코어의 Spring 전환은 ADR-002에 따라 계속한다.
현재 FastAPI AI 경로의 blocking OpenAI 호출은 전환 여부와 무관하게 즉시 async client 또는 제한된
thread offload로 교정해야 한다.

## 실험 대상과 공정성

- FL: 현재 `async def` 안의 동기 OpenAI 호출 의미를 재현한 FastAPI
- FS: shared async HTTP client, SSE upstream close, WebSocket disconnect cleanup을 적용한 FastAPI
- J: Java 25 + Spring Boot 4.1, virtual thread, JDK HTTP client, Spring WebSocket
- 모든 후보는 동일한 실제 TCP mock provider, payload와 지연을 사용했다.
- 애플리케이션별 2 CPU/1 GiB, Spring heap은 128–512 MiB로 고정했다.
- 본 측정은 warm-up 후 3회 실행의 중앙값이다.
- FS는 현재 project room이 process-local memory이므로 한 worker로 실행했다. 두 worker 민감도는
  별도로 실행하여 AI 확장 효과와 fan-out 정합성 손실을 분리했다.

## 본 측정

### AI generate

200 ms upstream 지연을 사용했다.

| 동시성 | 구현 | RPS | p95 | 실패율 | peak CPU | peak RSS |
|---:|---|---:|---:|---:|---:|---:|
| 10 | FastAPI legacy | 4.81 | 2,101 ms | 0% | 1.78% | 38.4 MiB |
| 10 | FastAPI safe | 47.16 | 224 ms | 0% | 27.67% | 41.1 MiB |
| 10 | Spring | 48.03 | 214 ms | 0% | 52.84% | 166.5 MiB |
| 100 | FastAPI legacy | 16.04 | 6,005 ms | 93.45% | 2.29% | 41.0 MiB |
| 100 | FastAPI safe | 65.09 | 4,924 ms | 1.21% | 92.39% | 47.0 MiB |
| 100 | Spring | 483.47 | 214 ms | 0% | 77.51% | 287.7 MiB |
| 300 | FastAPI legacy | 46.94 | 6,138 ms | 97.85% | 7.02% | 43.0 MiB |
| 300 | FastAPI safe | 53.57 | 6,027 ms | 77.55% | 98.47% | 70.0 MiB |
| 300 | Spring | 557.00 | 765 ms | 0% | 122.15% | 629.0 MiB |

300 동시성에서 Spring은 FS보다 RPS가 940% 높고 p95가 87.3% 낮았다. Spring run 세 개의
실패율은 0%, 0%, 0.51%로 중앙값 0%이며 모두 1% 미만이었다. 현재 blocking FL의 낮은 CPU는
효율이 아니라 event loop가 동기 upstream을 기다리며 요청을 직렬화한 결과다.

### SSE

100 ms 후 첫 event, 이후 50 ms마다 총 10개를 전송했다. 모든 연결이 10개 event를 정확히
수신했다.

| 동시 stream | 구현 | first-event p95 | 완전 수신률 | peak RSS |
|---:|---|---:|---:|---:|
| 20 | FastAPI safe | 365 ms | 100% | 69.0 MiB |
| 20 | Spring | 133 ms | 100% | 622.5 MiB |
| 100 | FastAPI safe | 699 ms | 100% | 66.9 MiB |
| 100 | Spring | 265 ms | 100% | 623.7 MiB |

100 stream에서 Spring first-event p95는 FS보다 62.1% 낮았다. client가 첫 event 뒤 연결을
종료한 검사에서도 두 구현 모두 provider active connection을 0으로 회수했다.

### WebSocket

모든 client를 한 project room에 연결하고 각 client echo와 단일 HTTP vote broadcast를 검사했다.

| 연결 | 구현 | 연결률 | echo p95 | broadcast 수신률 | peak RSS |
|---:|---|---:|---:|---:|---:|
| 100 | FastAPI safe | 100% | 15.40 ms | 100% | 66.9 MiB |
| 100 | Spring | 100% | 39.22 ms | 100% | 626.0 MiB |
| 500 | FastAPI safe | 100% | 58.42 ms | 100% | 69.6 MiB |
| 500 | Spring | 100% | 152.46 ms | 100% | 630.1 MiB |

정확성 gate는 둘 다 통과했다. 그러나 Spring의 echo p95는 100 연결에서 155%, 500 연결에서
161% 높아 사전 등록된 20% 비열등성 gate를 실패했다. 절대 152 ms가 제품 SLO를 만족하는지는
별도 제품 판단이지만, 제품 SLO가 없는 상태에서 실험 후 임계값을 바꾸지 않았다.

## 장애·취소·라우팅

FS와 J 모두 provider 503→502, timeout→504, timeout 후 회복, SSE 취소 후 upstream 회수,
WebSocket disconnect·재연결을 통과했다. proxy를 Spring으로 전환하고 FastAPI-safe로 rollback한
뒤 AI·SSE·WebSocket 신규 연결도 모두 성공했다.

기존 WebSocket 연결은 backend 사이로 이전되지 않으므로 client 재연결 계약이 필요하다. 측정된
proxy recreate 시간은 약 4.5초이며 무중단 전환 증거로 사용하지 않는다.

## 15분 혼합 soak

AI 50 concurrency, SSE 20 connection, WebSocket 100 connection을 동시에 유지했다.

| 구현 | 시간 | 처리 event | 실패율 | AI p95 | RSS 첫 구간 | RSS 마지막 구간 | 증가 | 재시작/OOM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FastAPI safe | 902.4초 | 108,629 | 0.177% | 6,134 ms | 67.2 MiB | 67.2 MiB | 0.0% | 0/0 |
| Spring | 900.9초 | 337,044 | 0% | 222 ms | 634.3 MiB | 635.0 MiB | 0.1% | 0/0 |

두 구현 모두 안정성 gate를 통과했다. Spring은 처리 여유와 tail latency가 우수했지만 RSS는
FastAPI의 9.45배다. Spring RSS는 안정적이어서 이번 15분 동안 누수로 보이지 않지만, 높은 기준
점유량은 인프라 비용과 pod density 위험이다.

## 사후 민감도: FastAPI 2 workers

이 검사는 사전 gate를 변경하지 않으며 단일-worker 효과를 분리하기 위해 추가했다.

| workload | 동시성/연결 | 중앙값 결과 |
|---|---:|---|
| AI | 100 | 97.81 RPS, p95 3,368 ms, 실패 1.12% |
| AI | 300 | 65.45 RPS, p95 5,998 ms, 실패 49.00% |
| WebSocket | 100 | echo p95 8.30 ms, broadcast 수신 75% |
| WebSocket | 500 | echo p95 133.38 ms, broadcast 수신 80% |

두 worker는 AI를 개선했지만 Spring 수준에는 미치지 못했다. 더 중요하게, HTTP broadcast를 받은
worker의 local room에 속한 socket만 메시지를 받아 99% 정확성 gate를 실패했다. FastAPI를 여러
worker/instance로 확장하려면 Redis pub/sub 같은 외부 fan-out이 필요하다. 이것은 Python의 한계가
아니라 현재 in-memory 설계의 한계다.

## 사전 gate 판정

| Gate | 결과 |
|---|---|
| AI 300 오류율 1% 미만 | 통과, Spring 각 run 0%, 0%, 0.51% |
| AI 300 p95가 FS보다 20% 넘게 악화되지 않음 | 통과, 87.3% 개선 |
| SSE 성공·완전 수신 99%, first-event 비열등 | 통과 |
| WebSocket 연결·echo·broadcast 정확도 99% | 통과 |
| WebSocket echo p95 비열등 | **실패, 500 연결에서 161% 악화** |
| 장애·취소·회복 | 통과 |
| 15분 soak 오류·OOM·재시작·RSS 증가 | 통과 |
| endpoint routing과 rollback | 통과 |

전체 전환은 모든 핵심 gate 통과가 조건이므로 선택지 1을 기각하고 선택지 2를 유지한다.

## 결정 후 실행 경계

1. ADR-002 범위인 project/node transaction core의 Spring 단계 전환은 계속한다.
2. 기존 FastAPI AI handler의 동기 OpenAI 호출은 async client 또는 제한된 offload로 즉시 교정한다.
3. AI·SSE·WebSocket ownership은 이번 ADR로 Spring에 넘기지 않는다.
4. Java 전체 전환을 다시 검토하려면 Spring WebFlux/Netty 또는 최적화된 Spring WebSocket 후보를
   별도 실험하고, 제품의 절대 latency SLO를 먼저 정한다.
5. 어떤 스택이든 multi-instance WebSocket에는 외부 pub/sub와 reconnect/resubscribe 계약이 필요하다.

## 한계

- 실제 OpenAI TLS, rate limit, token streaming, SDK retry와 비용을 mock provider가 재현하지 않는다.
- 인증, DB write, 실제 vote payload 크기는 포함하지 않았다.
- 15분 soak는 1~6시간 운영 검증을 대체하지 않는다.
- WSL2 단일 호스트의 순차 실행이며 cloud network와 autoscaling 결과가 아니다.
- Spring MVC WebSocket 후보를 측정했으며 WebFlux/Netty 전체를 평가하지 않았다.
- 500 connection은 후보 비교용이며 production 최대 연결 규모를 증명하지 않는다.
- 메모리 사용량은 측정했지만 cloud 가격표를 적용한 금액 산정은 하지 않았다.

원본 JSON, 초 단위 자원 표본, routing 결과와 민감도 결과를 모두 이 디렉터리에 보존했다.
요약 표는 `summary.md`, 실행 환경은 `environment.txt`에 있다.
