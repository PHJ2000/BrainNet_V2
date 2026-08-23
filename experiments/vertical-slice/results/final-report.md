# BrainNet Java 25 + Spring vertical slice 최종 보고서

- 실험일: 2026-08-20 KST
- 결정: 프로젝트·노드 트랜잭션 코어의 단계적 Spring 전환 채택
- 비결정: 전체 즉시 재작성, AI 기능 전환, WebSocket 전환

## 결론

실제 BrainNet project/node 계약을 축소 재현한 vertical slice에서 Java 25 + Spring 스택은
공정하게 보정한 FastAPI보다 성능이 명확히 좋았고, 정합성·계약 변경 검출·장애 진단·rollback
게이트를 모두 통과했다. 따라서 “Java가 일반적으로 더 빠르다”가 아니라 “이 트랜잭션 코어
후보 스택이 실제 목표 workload에서 더 높은 여유와 compile-time 변경 안전성을 보였다”는
근거로 단계적 전환을 채택한다.

## 최종 성능 결과

각 값은 15초 warm-up 후 30초 측정 3회의 중앙값이다. 애플리케이션별 2 CPU/1 GiB,
총 DB pool 30, 같은 PostgreSQL과 같은 schema/JSON 계약을 사용했다.

| VUs | 구현 | RPS | p95 | p99 | 오류율 | peak CPU | peak RSS |
|---:|---|---:|---:|---:|---:|---:|---:|
| 10 | FastAPI legacy | 218.73 | 86.86 ms | 103.77 ms | 0% | 97.37% | 55.6 MiB |
| 10 | FastAPI safe | 452.27 | 49.08 ms | 62.46 ms | 0% | 197.52% | 132.4 MiB |
| 10 | Spring | 3,432.36 | 16.69 ms | 32.88 ms | 0% | 200.67% | 208.6 MiB |
| 100 | FastAPI legacy | 307.73 | 707.27 ms | 1,327.38 ms | 0% | 97.78% | 61.8 MiB |
| 100 | FastAPI safe | 481.12 | 489.74 ms | 744.48 ms | 0% | 200.41% | 140.9 MiB |
| 100 | Spring | 3,618.93 | 72.72 ms | 102.78 ms | 0% | 233.67% | 242.4 MiB |
| 300 | FastAPI legacy | 311.54 | 3,446.76 ms | 5,242.90 ms | 1.07% | 97.87% | 73.4 MiB |
| 300 | FastAPI safe | 454.29 | 2,220.47 ms | 3,982.72 ms | 0.51% | 201.38% | 155.3 MiB |
| 300 | Spring | 4,064.93 | 168.23 ms | 272.59 ms | 0% | 244.21% | 648.2 MiB |

300 VU에서 Spring 대 FastAPI safe 차이는 다음과 같다.

- RPS: +794.8%
- p95: -92.4%
- p99: -93.2%
- 오류율: 0% 대 0.51%
- peak CPU: +21.3%
- peak RSS: 4.17배

CPU 수치는 Docker의 1초 peak 표본이라 평균 core 사용량이 아니다. Docker inspect에서 두
컨테이너의 CPU 제한은 모두 2 CPU로 확인했다. Spring 결과는 Java 언어만의 효과가 아니라
Spring MVC, virtual thread, JDBC, Hikari와 구현 형태를 합친 후보 스택의 결과다.

## 정합성

각 구현에 root 생성 100개와 같은 `expected_version=0` PATCH 100개를 각각 3회 실행했다.

- legacy FastAPI root 최종 개수: 6, 18, 29
- legacy FastAPI PATCH: 매회 100개 성공, 최종 version 100
- safe FastAPI: 매회 성공 1, 409 99, 최종 root 1/version 1
- Spring: 매회 성공 1, 409 99, 최종 root 1/version 1

현재 BrainNet의 `SELECT 후 INSERT` root 확인과 조건 없는 PATCH에는 실제 경쟁 문제가 있다.
다만 FS도 J와 동일하게 이를 해결했으므로 정합성은 Java의 자동 이점이 아니라 DB unique index와
atomic `UPDATE ... WHERE version=?` 설계의 결과다.

## 계약 변경 검출

`order_index` 생산자 필드를 rename하고 소비 코드는 그대로 둔 mutation 결과다.

| 구현 | build | runtime |
|---|---|---|
| 현재 Python toolchain | `py_compile` 성공 | Pydantic validation 실패 |
| Java | Maven test compile에서 실패 | 실행 전 차단 |

Java 오류는 `cannot find symbol: method order_index()`였다. 이 결과는 현재 저장소에 정적 Python
타입 검사가 없다는 조건의 비교다. mypy/pyright와 strict typing을 도입한 Python까지 Java가 항상
우월하다는 뜻은 아니다.

## 장애 진단과 rollback

validation, missing node, version conflict, 의도적 DB failure에 대해 FS와 J 모두 다음을 통과했다.

- 사전 정의된 HTTP status와 stable error code
- 요청·응답 `X-Trace-Id` 일치
- 같은 trace ID가 포함된 구조화 로그
- DB failure 후 project, membership, root가 남지 않는 transaction rollback

nginx proxy를 Spring backend로 전환해 Spring health 응답을 확인한 뒤 legacy FastAPI로
재생성하여 rollback 응답을 확인했다. 최초 cutover 11.2초에는 nginx image pull이 포함되어 있어
배포 성능 수치로 사용하지 않으며, rollback 검사는 2.8초였다. 무중단 운영을 주장하는 실험은 아니다.

## 메모리 위험

Spring default heap은 300 VU 순차 부하에서 919 MiB까지 증가했다. 사전 규칙에 따라
`-Xms128m -Xmx512m`로 다시 실행했으며 최종 peak RSS는 648.2 MiB, OOM과 restart는 0이었다.
그래도 FS보다 4.17배이므로 운영 전 실제 데이터 장시간 soak, JFR, GC pause, native memory
tracking이 필요하다. 컨테이너는 heap을 명시적으로 제한해야 한다.

## 프로토콜 보정

정식 결과 도중 발견한 환경 오류는 결과를 삭제하지 않고 `protocol-corrections/`에 보존했다.

1. FS single worker 결과: 2 CPU 중 한 코어만 사용
2. FS worker 2×pool 30 결과: 총 pool 60이라 고정 조건 위반
3. Spring default heap 결과: RSS 919 MiB로 사전 재실험 조건 충족
4. Spring heap 512 결과: background FS pool 60이 전체 DB connection 표본에 포함

최종 결과는 FS worker 2×pool 15, Spring pool 30/heap 512이며 측정 시 PostgreSQL 전체
connection peak가 두 구현 모두 34였다. 사전 판정 기준은 변경하지 않았다.

## 한계

- 실제 BrainNet schema와 API 모양을 축소한 vertical slice이며 인증·태그·투표 전체를 포함하지 않았다.
- FastAPI는 SQLAlchemy text query, Spring은 JdbcTemplate을 사용했다. ORM entity 생산성 비교가 아니다.
- 실제 데이터 분포, production VM, 네트워크 TLS와 proxy 비용을 포함하지 않았다.
- WebSocket fan-out과 OpenAI 호출은 제외했다.
- 30초 측정이므로 장시간 GC, connection leak, 메모리 안정성을 증명하지 않는다.
- compile mutation 하나는 변경 안전성의 대표 표본이지 개발 생산성 전체의 정량화가 아니다.
- proxy 검사는 route 전환 가능성만 증명하며 무중단 cutover를 증명하지 않는다.

## 실행 결정과 경계

채택 범위는 project/node transaction core의 endpoint 단위 strangler migration이다.

1. DB에 active-root unique constraint와 node `version`을 expand migration으로 추가한다.
2. 같은 OpenAPI contract test를 legacy와 Spring에 적용한다.
3. Spring read endpoint를 shadow traffic으로 검증한다.
4. node PATCH의 write owner를 Spring 하나로 옮겨 canary한다.
5. 오류율·p95·heap gate를 통과하면 project/node endpoint를 전환한다.
6. 실패 시 proxy를 legacy로 되돌린다.
7. 안정화 후 contract migration을 수행한다.

AI와 WebSocket은 FastAPI에 유지한다. 전체 재작성은 이번 ADR의 결정이 아니다.

