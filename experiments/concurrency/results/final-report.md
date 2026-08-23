# BrainNet Java 25 concurrency experiment report

- 실험일: 2026-08-20 KST
- 결론: Java 25의 동시성 성능을 근거로 한 전체 Spring 전환은 채택하지 않는다.
- 채택안: FastAPI를 우선 교정하고, Java 전환은 별도 유지보수성/도메인 근거와 실제 vertical
  slice 증거가 생길 때 다시 결정한다.

## 직접 결론

Java 25 가상 스레드는 효과가 있었다. 500 VU, 200 ms blocking I/O에서 Spring virtual은
Spring platform보다 RPS가 168.1% 높고 p95가 61.6% 낮았다. 따라서 높은 blocking I/O
동시성에서 platform thread cap을 제거하는 수단으로 유효하다.

하지만 올바르게 작성한 FastAPI asyncio와 비교하면 Java 우위는 확인되지 않았다. 같은
500 VU I/O에서 FastAPI async는 2,666.47 RPS / p95 210.73 ms, Spring virtual은
2,637.96 RPS / p95 216.01 ms였다. Spring virtual의 RPS는 1.1% 낮고 p95는 2.5% 높아
사전 판정 기준 20%를 충족하지 못했다.

현재 BrainNet과 같은 blocking FastAPI 구현은 명확히 문제가 있었다. 100 VU에서 오류율
63.81%, 500 VU에서 90.43%였고 p95는 모두 약 10초 timeout에 도달했다. 그러나 같은
FastAPI를 올바른 async 대기로 바꾸자 500 VU에서 오류 없이 2,666.47 RPS를 처리했다.
따라서 이 차이는 Java의 승리가 아니라 현재 동기 OpenAI SDK 호출의 event-loop 차단이다.

## 주요 결과

모든 값은 30초 측정 3회의 중앙값이다. 각 조합 전에 15초 warm-up을 수행했다.

| 워크로드 | 구현 | RPS | p95 | 오류율 | peak CPU | peak RSS |
|---|---|---:|---:|---:|---:|---:|
| I/O 200 ms, 500 VU | FastAPI current | 52.04 | 10,000.94 ms | 90.43% | 0.36% | 33.4 MiB |
| I/O 200 ms, 500 VU | FastAPI async | 2,666.47 | 210.73 ms | 0% | 30.70% | 44.8 MiB |
| I/O 200 ms, 500 VU | Spring platform | 984.09 | 562.67 ms | 0% | 72.18% | 226.5 MiB |
| I/O 200 ms, 500 VU | Spring virtual | 2,637.96 | 216.01 ms | 0% | 47.33% | 884.6 MiB |
| DB 50 ms, pool 30, 500 VU | FastAPI async | 515.32 | 1,967.60 ms | 0% | 89.54% | 47.7 MiB |
| DB 50 ms, pool 30, 500 VU | Spring platform | 583.88 | 1,129.11 ms | 0% | 38.95% | 246.4 MiB |
| DB 50 ms, pool 30, 500 VU | Spring virtual | 574.53 | 1,652.15 ms | 0% | 33.67% | 439.0 MiB |

전체 중앙값 표는 `summary.md`, 반복별 값은 `load-results.csv`, k6 원본은 `raw/`, 1초
간격 컨테이너 자원 표본은 `stats/`에 있다.

## 판정 기준 적용

### Spring virtual 대 FastAPI async

- I/O 500 VU: RPS -1.1%, p95 +2.5%, CPU +54.2%, RSS 약 19.7배
- DB 100 VU: RPS +6.4%, p95 -31.5%, peak CPU -56.4%, RSS 약 5.0배
- DB 500 VU: RPS +11.5%, p95 -16.0%, peak CPU -62.4%, RSS 약 9.2배

DB에서 CPU와 일부 latency 이점은 확인되었지만 처리량 20% 기준은 충족하지 않았다. CPU는
1초 표본의 peak이고 반복 간 편차가 있어 이것만으로 전체 마이그레이션을 정당화하지 않는다.
특히 DB 500 VU에서는 Spring platform이 virtual보다 RPS가 1.6% 높고 p95가 31.7% 더
낮았다. DB pool처럼 동시성이 이미 30으로 제한된 경로에서는 virtual thread가 더 나은 선택이라고
볼 수 없다.

### Spring virtual 대 Spring platform

- I/O 500 VU: RPS +168.1%, p95 -61.6%, peak CPU -34.4%
- DB 500 VU: RPS -1.6%, p95 +46.3%, peak CPU -13.6%

가상 스레드의 이점은 높은 blocking I/O에서 뚜렷했지만 제한된 DB pool에서는 없었다.

### 메모리

Spring virtual은 순차 부하 실행 중 JVM committed memory가 증가하여 I/O 500 VU에서
median peak RSS 884.6 MiB까지 도달했다. 컨테이너 제한 1 GiB에 가깝다. 이는 가상 스레드
자체의 고정 비용만으로 해석할 수 없고 heap/GC/JIT/부하 순서의 누적 효과가 포함되지만,
현재 설정을 그대로 운영에 채택하기 전에 JFR/GC 및 heap 제한 실험이 필요하다는 위험 신호다.

## 정합성 결과

새 project ID 12개에 각각 100개 동시 root 생성 요청을 보냈다.

- 모든 12회: HTTP 201 정확히 1개
- 모든 12회: HTTP 409 정확히 99개
- 예상 밖 상태: 0개
- 최종 DB row: project마다 정확히 1개

FastAPI와 Spring 모두 같은 결과였다. 정합성을 만든 것은 언어가 아니라 PostgreSQL primary
key와 `INSERT ... ON CONFLICT DO NOTHING`이다. 현재 BrainNet root node에는 이에 해당하는
DB constraint가 없으므로 Java 전환과 무관하게 먼저 보완해야 한다.

## 프로토콜 보정과 폐기한 결과

1. 첫 정식 런에서 blocking FastAPI의 timeout 요청이 서버 queue에 남아 다음 반복을 오염시킬
   수 있음을 발견했다. 해당 결과는 `aborted-backlog-contamination/`에 보관하고, 각 F0 측정
   직후 컨테이너를 재시작하여 다시 측정했다.
2. 네 서비스의 pool 합계 120이 PostgreSQL 기본 `max_connections=100`을 넘었다. 해당 DB
   결과는 `aborted-postgres-max-connections/`에 보관하고 `max_connections=200`을 health
   check로 확인한 뒤 DB 전체를 다시 측정했다.
3. 스모크와 project ID가 겹친 정합성 결과는 `aborted-reused-project-ids/`에 보관하고 새
   ID 910001~910012로 다시 실행했다.

이 보정들은 결과를 본 뒤 판정 기준을 바꾼 것이 아니라 반복 독립성과 자원 조건을 회복하기 위한
것이다. 폐기 데이터도 추적 가능하게 남겼다.

## 한계

- 실제 인증, ORM entity mapping, JSON payload 크기와 전체 BrainNet API를 포함하지 않은
  representative concurrency harness다.
- 외부 OpenAI 대신 결정적인 `sleep`을 사용했다.
- WebSocket fan-out은 이번 실험에 포함하지 않았다.
- FastAPI는 현재 배포와 같은 worker 1개다. corrected async 비교군도 worker 1개라 I/O 비교는
  공정하지만 CPU-bound/multi-process 비교는 아니다.
- WSL2 단일 호스트 실험이며 production 네트워크/VM 결과가 아니다.
- CPU와 RSS는 Docker 1초 표본의 peak다. 정밀 profiling 결과가 아니다.

## 최종 권고

1. 현재 `openai.chat.completions.create`를 async client 호출로 교체한다.
2. root uniqueness, 투표, 노드 update 정책을 DB constraint와 optimistic version으로 정의한다.
3. 프로세스 메모리 WebSocket registry를 Redis/pub-sub 같은 외부 상태로 옮기기 전에는 Uvicorn
   worker 확장을 하지 않는다.
4. Java 전환을 계속하려면 “Java 25가 더 빠르다”가 아니라 타입 안정성, 팀 학습 목표,
   트랜잭션 모델, 운영 도구 같은 별도 근거로 새 ADR을 만든다.
5. 그 ADR에서는 실제 노드 PATCH vertical slice, WebSocket fan-out, JFR/GC memory 실험을
   통과한 뒤 endpoint 단위 strangler migration을 결정한다.

