# BrainNet V2 리팩토링 구현·검증 결과

> **1차 구현 당시의 기록이다.** 아래의 미수행 항목과 수치는 당시 조건에 한정한다. 후속 구현, 원격 CI, 전체 부하 행렬, 실패·복구 결과는 [최종 검증 보고서](REFACTORING_COMPLETION_2026-09-12.md)를 따른다.

확인일: 2026-09-12. 기준 커밋 `be75d7a99c827dd225bee3e12d49cb5be1062bd3`, 작업 브랜치 `fix/node-request-contracts`의 로컬 변경이다. [검토 초안](REFACTORING_REVIEW_DRAFT_2026-09-12.md)을 바탕으로 요청 계약·이벤트 전달을 구현하고 전용 Docker DB에서 검증했다. 원격 CI 실행·커밋·push·운영 전환은 수행하지 않았다.

## 결과

**중복 생성 방지를 실제 프론트 요청부터 두 백엔드까지 연결했고, Spring 생성 이벤트가 FastAPI 여러 인스턴스의 접속자에게 전달되도록 구현했다.** 동일 계약을 수행하는 실제 앱의 일반 노드 생성 비교에서는 Spring이 FastAPI보다 처리량 90.9% 높고 p95 35.8% 짧았다.

이 수치는 이번 변경 전후의 서비스 전체 개선율이 아니라, **변경 후 FastAPI와 Spring 후보의 같은 작업 비교**다. 기본 Compose의 요청 경로는 FastAPI다.

## 구현한 내용

| 문제 | 변경 | 확인한 증거 |
| --- | --- | --- |
| 프론트 재시도마다 중복 노드가 생길 수 있음 | 생성 동작별 멱등성 키, 전송 재시도 시 재사용, AI 일부 성공 후 미완료 슬롯만 재개 | 응답 유실·부분 성공·fallback 고정·프로젝트 이동 테스트 |
| FastAPI와 Spring 간 완료 응답 재사용 불가 | 공통 fingerprint v1, 프로젝트·본문 충돌 검사, 완료 응답 24시간 보존, 만료 claim의 이전 처리자 차단 | 양방향 재사용, 두 런타임에 같은 키로 100개 동시 요청해 노드·Outbox 각 1개 |
| 노드 저장과 이벤트·완료 응답의 분리 위험 | 노드·상속 태그·완료 응답·Outbox를 같은 트랜잭션에 저장 | Outbox 저장 실패 시 전체 rollback, provider 실패 후 정상 재시도 |
| 기본 설정에서 버전 없는 수정 허용 | `REQUIRE_NODE_VERSION=true` 기본값 | 버전 누락 428, 오래된 버전 409, 동시 수정 100건 중 1건 성공 |
| Outbox 기록 후 외부 전달 경로 없음 | PostgreSQL 알림으로 FastAPI worker 전체에 전달, event_id 중복 억제, 재접속 시 DB 재조회 | 두 FastAPI 인스턴스 수신, 중복 알림 억제, DB listener 강제 종료 후 복구 |
| CI의 추가 DB 검증이 실행되지 않을 수 있음 | `docker exec -i` 수정, SQL 증명과 이벤트 probe·프론트 테스트 추가 | 의도적 Python exit 7이 수정 전에는 0, 수정 후에는 7로 전달됨 |

유지보수 측면에서는 Python·Java의 멱등성 처리를 서비스로 분리하고, Graph의 자식 생성 계획·요청 재시도·이벤트 연결을 별도 모듈로 추출했다. API 주소는 `NEXT_PUBLIC_API_BASE_URL`로 설정할 수 있다. 전체 HTTP·도메인·provider 계층 분리는 후속 범위다.

## 실제 앱 부하 측정

조건: 일반 노드 생성, 동시 요청 100개, 5초 warm-up 후 60초 × 3회, 회차별 실행 순서를 교대했다. 각 앱 2 CPU·1 GiB, Spring heap 512MiB, DB pool 최대 30개, 같은 PostgreSQL 15 전용 DB를 사용했다. JWT 인증·멤버십·부모 확인·태그 상속·새 멱등성 키·Outbox 저장을 포함했다.

FastAPI 2개 인스턴스에서 이벤트 bridge를 켠 상태이고, 요청은 한 인스턴스로 보냈다. 각 bridge는 pool 외에 DB 연결 2개를 사용한다. 부하 발생기와 DB는 같은 Docker Desktop 호스트에 있으며 별도 자원 제한을 설정하지 않았다. WebSocket 클라이언트와 브라우저 재조회 부하는 포함하지 않았다.

아래는 **각 회차 지표의 중앙값**이다. 모든 요청의 지연을 하나로 합친 분포는 아니다.

| 지표 | FastAPI | Spring | 차이 |
| --- | ---: | ---: | ---: |
| 성공 처리량 | 139.497 RPS | 266.257 RPS | **1.909배, +90.9%** |
| p50 | 468.625ms | 225.759ms | |
| p95 | 1,915.249ms | 1,229.016ms | **35.8% 감소** |
| p99 | 2,964.701ms | 2,020.906ms | |
| 오류율 | 0% | 0% | 모든 회차 |

| 런타임 | 회차 | 성공 건수 | 성공 RPS | p95(ms) | 종료 직후 미발행 이벤트 |
| --- | ---: | ---: | ---: | ---: | ---: |
| FastAPI | 1 | 9,111 | 150.765 | 1,768.110 | 14 |
| FastAPI | 2 | 8,230 | 136.040 | 1,921.710 | 36 |
| FastAPI | 3 | 8,441 | 139.497 | 1,915.249 | 27 |
| Spring | 1 | 16,032 | 266.257 | 1,229.016 | 79 |
| Spring | 2 | 17,244 | 286.450 | 1,069.505 | 26 |
| Spring | 3 | 14,581 | 241.522 | 1,283.303 | 44 |

측정 구간의 **73,639건 모두 201**, 각 회차 성공 수와 실제 DB 증가 행 수가 일치했다. warm-up은 이 건수에서 제외했다. 앱 컨테이너에서 OOM·자동 재시작은 없었다. 처리량은 DB commit 응답 기준이며 이벤트 수신 완료까지의 처리량은 아니다. 회차 종료 직후 미발행 14~79건이 관찰됐고, 해당 backlog가 비워지는 시간은 측정하지 않았다. CPU/RSS 시계열과 DB 대기시간도 이번 결과에는 없다.

기존 초안의 3.42배는 mock AI provider를 사용한 축소 앱·동시 요청 300개 실험이다. 이번 결과와 조건이 달라 직접적인 전후 비교에 사용하지 않는다.

재현 방법: [실행 안내](../experiments/runtime-nodes/README.md). [회차별 원본 JSON](../experiments/runtime-nodes/results/2026-09-12/), [집계·환경 기록](../experiments/runtime-nodes/results/2026-09-12/summary.json).

## 검증

- Python **48개 통과**: 기존 일반 36개 + PostgreSQL 동시성 5개 + 멱등성 6개 + 이벤트 원자성 1개. PostgreSQL 테스트를 생략하지 않고 전용 DB에서 실행했다.
- Java 25 / Testcontainers **19개 통과**: 기존 15개 + 프로젝트 간 키 충돌·동시 재시도·만료 claim 차단·Outbox 실패 rollback.
- 프론트 **7개 통과**, Next.js production build 성공. 브라우저 화면 E2E는 수행하지 않았다.
- 최종 production Docker 이미지 두 개 빌드 및 실행 성공. 실제 HTTP differential probe와 두 인스턴스 WebSocket 복구 probe 통과.
- CI YAML과 16개 shell run 블록의 Bash 문법 확인. 이는 원격 GitHub Actions 전체 실행 결과를 대신하지 않는다.

자동 테스트 합계는 기존 56개에서 **74개로 18개 증가**했다. 테스트 수 증가를 코드 커버리지 증가율로 해석하지 않는다. 기존 Pydantic·pytest-asyncio 등의 경고는 남아 있다.

## 다음 단계와 배포 제약

1. **추가 계측:** 동시 요청 10·300개, 실제 provider의 429·timeout·취소, 1~6시간 부하, CPU/RSS·DB 대기·이벤트 지연을 측정한다. 클라이언트 재조회 비용과 절대 p95 목표도 확인한다.
2. **이벤트 운영:** 생성 외 수정·삭제·vote 전달을 확장하고, Outbox·만료 claim 정리 정책과 모니터링 경보를 추가한다. 현재 `/health/events`는 준비 상태·미발행 건수·최장 대기시간·발행 실패 횟수를 제공한다.
3. **경로 전환:** proxy와 프로젝트 단위 고정 라우팅을 마련한 staging에서 synthetic 쓰기·소규모 canary·rollback을 검증한다. 일반 생성과 AI 생성의 write owner를 함께 전환한다.

현재 이벤트 계약은 재조회에 의한 **최종 상태 복구**다. 모든 과거 이벤트 재생을 보장하지 않는다. 프론트의 미완료 생성 계획은 현재 화면의 메모리에 있으므로 새로고침을 넘어서 유지되지 않는다.

기존 Spring의 Jackson hash와 새 fingerprint v1은 호환되지 않는다. 이전 유효 claim이 있는 배포 환경에서는 진행 중 요청을 끝내고 기존 24시간 보존 창이 지난 뒤 두 구현을 함께 갱신해야 한다. rollback은 v1 지원 FastAPI를 대상으로 한다. 자세한 내용은 [요청·이벤트 계약](migration/node-request-and-event-contract.md)에 정리했다.
