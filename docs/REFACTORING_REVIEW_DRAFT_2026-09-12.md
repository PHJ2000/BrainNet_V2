# BrainNet V2 리팩토링 평가·개선 초안

최종 진행 결과: [구현·성능·운영 전환 판단](REFACTORING_COMPLETION_2026-09-12.md).

> 이 문서는 구현 전 검토 기록이다. 후속 구현·전용 Docker 검증·실제 앱 부하 측정 결과는 [리팩토링 결과](REFACTORING_RESULT_2026-09-12.md)에 정리했다. 아래의 "현재"와 "미수행"은 초안 작성 시점을 뜻한다.

확인일: 2026-09-12. 비교 범위: 리팩토링 전 `dd9b820` → 현재 main `be75d7a`.
로컬 HEAD와 GitHub main이 일치한다. PR #1~#4는 병합됐고, 운영 전환 절차를 다루는 [PR #5](https://github.com/PHJ2000/BrainNet_V2/pull/5)는 열려 있다.

## 판단

**동시성 정합성과 검증 기반은 개선됐다. Spring 후보의 부하 처리 성능도 좋아졌지만, 서비스 전체의 성능 개선율은 아직 측정되지 않았다.**

기본 Compose는 여전히 FastAPI를 실행한다. Spring 구현은 별도 서비스이며 운영 요청 경로에 연결되어 있지 않다. 따라서 아래 3.42배를 현재 사용자 체감 속도나 운영 처리량 개선율로 쓰면 안 된다.

## 얼마나 개선됐나

### AI 호출부터 노드 저장까지: FastAPI safe와 Spring 후보 비교

조건: 축소 구현, mock provider 200ms, 동일 PostgreSQL, 앱별 2 CPU·1 GiB, DB pool 총 30. 동시 요청 300건, 10초 측정 3회의 지표별 중앙값이다.

| 지표 | FastAPI safe | Spring 후보 | 변화 |
| --- | ---: | ---: | ---: |
| 처리량 | 161.12 RPS | 550.47 RPS | **3.42배, +241.7%** |
| p95 응답시간 | 4,060.74ms | 881.59ms | **78.3% 감소** |
| 오류율 중앙값 | 약 1.6% | 0% | 약 1.6%p 감소 |
| 부하 직후 RSS | 168.7MiB | 317.7MiB | **88.3% 증가** |

동시 요청 10건에서는 처리량 1.24배, 100건에서는 3.27배였다. 이득은 부하 수준에 따라 다르다.

이번 확인에서 원본 JSON 18개의 지표를 다시 집계했다. CSV의 소수 셋째 자리 반올림 규칙을 적용하면 중앙값이 일치한다. FastAPI의 오류율 원본 중앙값은 0.016119이며 CSV에는 0.016으로 저장돼 있다. Spring도 한 회차에서 오류율 0.8775%가 나왔으므로 모든 요청이 무오류였다는 뜻은 아니다.

근거: [최종 보고서](../experiments/ownership-split/results/final-report.md), [CSV](../experiments/ownership-split/results/measurements.csv), [원본 결과](../experiments/ownership-split/results/raw/), [집계 코드](../experiments/ownership-split/analyze.py).

### 정확성·유지보수성

| 항목 | 이전 또는 비교 실험 | 현재 확인된 개선 |
| --- | --- | --- |
| 같은 버전의 수정 100건 | legacy 축소 구현에서 100건 모두 성공, version 100까지 증가 | safe/Spring 실험은 성공 1건·409 충돌 99건·version 1회 증가. 실제 구현 CI에도 동시 수정 검증 존재 |
| 활성 루트 중복 | legacy 축소 구현 3회 중 활성 루트 1·8·14개 | safe/Spring은 매회 1개. 실제 FastAPI에 부분 unique index와 PostgreSQL 회귀 테스트 추가 |
| AI 대기 | 동기 SDK 호출로 event loop를 막던 구조 | FastAPI `AsyncOpenAI` 적용, provider 대기 전에 DB 연결 반환, 저장 시 멤버십·부모 재검증 |
| 재시도·이벤트 저장 | 별도 보호 계약 부재 | Spring 생성 경로에 멱등성 응답과 node.created Outbox 원자적 저장 구현. 키를 보낸 요청에 한해 멱등성 적용 |
| 자동 검증 | 비교 기준 커밋에 backend/tests·Spring·CI 경로 없음 | 현재 main CI 로그: FastAPI 일반 36개 + PostgreSQL 5개 + Spring 15개 통과 |

정합성 비교 수치는 [vertical-slice 실험](../experiments/vertical-slice/results/summary.md)이며, 과거 운영 장애 빈도나 실제 데이터 유실 건수 측정은 아니다.

[현재 main의 CI](https://github.com/PHJ2000/BrainNet_V2/actions/runs/32740948329)는 2026-08-24 실행분이다. 이번에 그 로그와 SHA를 다시 확인했다. 첫 pytest에서 건너뛴 PostgreSQL 5개는 별도 단계에서 모두 통과했다. 프론트 빌드 및 FastAPI/Spring 계약 probe도 성공했다.

### 전체 Spring 전환을 보류한 근거

WebSocket 500개 연결 실험에서 echo p95는 FastAPI safe 58.42ms → Spring 152.46ms로 약 161% 악화됐다. 별도 2-worker FastAPI 실험에서는 broadcast 수신률이 75~80%였다. 현재 프로세스 메모리의 연결 목록만으로는 여러 인스턴스에 이벤트를 전달할 수 없다.

근거: [실시간 통신 실험](../experiments/realtime-ai/results/final-report.md), [현재 연결 관리자](../backend/app/utils/ws_manager.py).

## 다음 작업 초안

### 1. 검증 누락과 사용자 요청 계약부터 닫기

- **CI DB 검증 실행 보완:** [ci.yml](../.github/workflows/ci.yml)의 `docker exec ... python - <<'PY'`에 `-i`가 빠져 있다. 정적 검토상 here-document가 컨테이너 Python에 전달되지 않는 형태이며, 성공 문구도 조회한 로그에서 스크립트 본문에만 보였다. `docker exec -i` 또는 컨테이너에 복사한 파일 실행으로 바꾸고, 검증을 일부러 실패시켰을 때 job이 실패하는지 확인한다. 기존 Spring 통합 테스트·계약 probe 통과와 이 추가 SQL 검증의 실행 여부는 구분한다.
- **멱등성 키를 실제 생성 요청에 연결:** [nodeApi.ts](../frontend/src/features/nodes/nodeApi.ts)의 일반·AI 생성 요청과 공통 axios client는 `Idempotency-Key`를 보내지 않는다. 사용자 생성 동작마다 키를 만들고 동일 요청 재시도에서는 재사용한다. Spring은 현재 키 없이도 생성을 허용한다.
- **FastAPI 유지·rollback 경로도 같은 계약 보장:** 기본 FastAPI에는 멱등성 테이블 모델만 있고 생성 처리에서 사용하지 않는다. 기본 서비스에서 중복 방지를 제공하려면 해당 경로에도 처리 구현이 필요하다. rollback 뒤에도 같은 키의 응답을 재사용하도록 양쪽 계약을 맞춘다.
- **버전 필수화:** 프론트는 `expected_version`을 보내지만 기본 Compose의 `REQUIRE_NODE_VERSION`은 false다. 기존 호출자 점검 후 true로 전환해 버전 없는 오래된 수정 요청까지 차단한다.

완료 기준: 응답 유실 후 같은 키로 재시도해도 node·outbox 각 1개, 다른 본문에 같은 키를 쓰면 충돌, 이전 버전 수정은 409, 버전 누락은 정의된 오류로 거절. FastAPI/Spring 및 rollback 시나리오를 함께 검증한다.

### 2. Outbox에서 WebSocket까지 이벤트 전달 완성

현재 Spring은 Outbox에 기록하지만 publisher·외부 전달·FastAPI consumer가 없다. 우선 node.created 한 종류부터 발행 상태, 재시도, event_id 중복 처리, 실패 후 복구를 구현한다.

여러 FastAPI 인스턴스가 각자의 접속자에게 이벤트를 전달하도록 설계한다. 단순 Pub/Sub만 선택하면 끊긴 동안의 이벤트 복구는 별도 구현이 필요하다. 영속 전달 또는 DB 재조회 기반 재동기화 중 하나를 계약으로 명시한다. 같은 이벤트를 모든 인스턴스가 받아야 하는 fan-out과 한 작업자만 처리하는 queue를 구분한다.

완료 기준: FastAPI 2개 인스턴스의 클라이언트가 모두 생성 이벤트 수신, 중복 이벤트에도 화면 노드 1개, consumer 재시작·재접속 후 서버 상태와 일치, 미발행 건수·최장 대기시간 관측 가능.

### 3. 실제 구현으로 성능을 다시 측정한 뒤 경로 전환

- 실험용 앱 대신 `backend/`와 `spring/vertical-slice/`를 동일한 인증·멤버십·태그·DB 스키마·이벤트 전달 조건으로 비교한다.
- 저부하/100/300 동시 요청, warm-up 후 최소 60초씩 3회 측정하고 결과를 회차별로 보존한다. 처리량은 전체 요청과 성공 요청을 나누고 p50/p95/p99, 오류율, DB 대기·연결, CPU/RSS, Outbox 지연을 기록한다.
- 실제 provider의 429·timeout·취소·응답 파싱을 staging에서 검증한다. 짧은 실험 후 1~6시간 soak로 메모리와 backlog 증가를 확인한다.
- 배포 경로에 proxy를 마련하고 [apiClient.ts](../frontend/src/lib/apiClient.ts)의 고정 `http://localhost:8000`을 배포 설정에 연결한다. 일반·AI 생성은 같은 POST 경로의 동일 write owner로 보낸다.
- 제안 순서: 읽기 shadow → 격리된 synthetic 쓰기 → 프로젝트 단위로 고정한 소규모 canary → 확대. 운영 POST 이중 쓰기는 하지 않는다. rollback 후 멱등성과 이벤트 처리를 포함해 복구를 확인한다.

제안 통과 기준: 동시성 정합성 위반 0건, 각 부하 회차 오류율 1% 미만, p95가 비교 대상보다 20% 넘게 악화되지 않음, OOM·restart 0건, 이벤트 복구 성공. 이는 이번 초안의 기준이며 제품의 절대 응답시간 목표는 별도로 정해야 한다.

### 4. 동작이 고정된 뒤 책임별로 코드 분리

현재 [nodes.py](../backend/app/routers/nodes.py)는 461줄, [VerticalService.java](../spring/vertical-slice/src/main/java/com/brainnet/spring/VerticalService.java)는 449줄, [Graph.tsx](../frontend/src/features/nodes/Graph.tsx)는 871줄이다. 길이 자체보다 변경 책임이 모여 있다는 점이 문제다.

- Python: HTTP 라우터 / 노드 트랜잭션 서비스 / AI provider client.
- Java: 노드 생성·수정 / provider client / 멱등성 저장 / Outbox 발행.
- 프론트: 그래프 렌더링 / 서버 상태·충돌 복구 / 노드 조작.

분리할 때 노드·태그·멱등성 응답·Outbox의 원자적 저장 경계와 provider 대기의 위치를 유지한다. 회귀 테스트 통과와 외부 응답 계약 유지를 완료 기준으로 삼고, 파일 수나 줄 수 감소를 성능 개선으로 계산하지 않는다.

## 이번 확인 범위

- 수행: 로컬·원격 SHA 대조, PR 상태·현재 main CI 로그 조회, 구현·프론트 요청·Compose 대조, 저장된 부하 원본 18개 재집계.
- 미수행: 새로운 부하 실험, 실제 AI 호출, 로컬 테스트 재실행, 운영 전환. 로컬 Docker daemon 연결이 실패했고 PATH에 Python·Maven이 없으며 Java는 17이라, 신규 런타임 검증으로 표현하지 않았다.
- 변경: 이 초안 문서만 추가했다. 기존 README·문서 변경은 그대로 두었다.
