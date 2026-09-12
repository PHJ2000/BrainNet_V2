# BrainNet V2 고부하 시간 초과 후속 수정

2026-09-12 · 구현 커밋 `2adbcc1` · [PR #6](https://github.com/PHJ2000/BrainNet_V2/pull/6)

**수정, 기능 검증, 60초 반복 부하 및 엄격한 1시간 연속 검증을 완료했다.** 이전 실패 기록은 삭제하지 않는다.

## 수정한 부분

- FastAPI의 일반·AI 생성에 각각 동시 실행 32개, 대기 512개, 대기 제한 5초를 적용했다. 대기 중에는 DB 연결이나 멱등성 claim을 잡지 않으며 AI 대기열이 일반 생성을 막지 않는다.
- 대기열 포화·시간 초과는 `503 NODE_CREATION_BUSY`, `Retry-After: 1`로 알린다. 프론트는 같은 키로 1초 뒤 최대 두 번 재시도하고 AI fallback을 실행하지 않는다. 대기·실행 중 취소에도 자리를 반환한다.
- 실행·대기·거절 수를 종류별 Prometheus 지표로 노출했다. provider 2초, 부하 클라이언트 10초 timeout은 그대로다. 부하 검증에서 503도 실패로 집계한다.
- 부하 발생기를 4개 프로세스로 나누고 HTTP 풀당 동시 요청을 20개로 제한했다. 총 동시 요청 수는 그대로다. 요청 지연을 합쳐 percentile을 계산하며, 프로세스별 CPU 비율과 event-loop 지연을 함께 저장한다.
- 모니터 연결 실패가 전체 측정 결과를 유실시키지 않도록 바꿨다. 연속 검증은 접속자별 이벤트 수, 오류 단계·키, 클라이언트/provider fixture의 event-loop 지연을 기록한다. 자원 수집기의 종료 시한도 monotonic clock을 사용한다.

## 원인 확인과 측정 해석

기존 단일 HTTP 풀을 CPU 프로파일링하면 약 6,676만 함수 호출 중 연결의 `is_idle` 검사가 약 5,095만 회였다. 풀 상태 변경마다 연결 목록을 반복 탐색하는 비용이 컸다. 풀을 나눈 뒤에도 Spring 부하에서는 발생기 한 코어의 CPU 비율이 약 91%여서, 최종 측정에서는 4개 프로세스로 분산했다. 이 변경으로 올라간 처리량을 애플리케이션 리팩터링의 개선율로 해석하지 않는다.

발생기 CPU에 여유가 있는 FastAPI 진단에서도 시간 초과가 남았다. 별도 실행한 실제 앱에서 생성·provider·DB 실행 구간을 측정한 뒤 동시 실행을 32개로 제한하자, AI 300동시 요청의 짧은 진단 회차는 오류 0건으로 끝났다. 미들웨어 교체와 provider 연결 수만 조정한 후보는 효과가 없어 되돌렸다. DB 풀은 기존 10개 + overflow 20개를 유지한다.

최종 조건은 앱별 2 CPU·1 GiB, FastAPI worker 1개, Spring virtual threads, 런타임별 최대 DB 연결 30개, 같은 PostgreSQL 15, 200ms 로컬 HTTP provider fixture다. FastAPI 이벤트 worker의 publisher/listener 연결 2개는 별도다. 일반·AI 각각 C100/C300, 5초 준비 후 60초 × 3회이며, 같은 호스트에서 다른 부하·빌드를 겹치지 않는다. 실제 OpenAI의 TLS·rate limit·생성 품질이나 운영 트래픽 검증은 포함하지 않는다.

## 기능 검증

Python 57개(실제 PostgreSQL 동시성 포함), 프론트 단위 8개가 로컬에서 통과했다. 원격 CI는 Spring 19개와 Chromium E2E 1개, build/lint, Alembic round-trip, HTTP 계약 비교, provider 오류 응답, 두 인스턴스 이벤트 복구, canary·rollback까지 통과했다. 일반 테스트 합계는 85개이며 코드 커버리지 비율은 아니다.

[구현 커밋의 CI](https://github.com/PHJ2000/BrainNet_V2/actions/runs/34686564267), [같은 커밋의 다른 트리거 CI](https://github.com/PHJ2000/BrainNet_V2/actions/runs/34686562816).

## 실제 사용할 로컬 앱

외부 서버를 구매하거나 배포하지 않고 이 PC의 Docker에서 Next.js + FastAPI + PostgreSQL을 실행한다. `deploy/start-local.ps1`로 켜고 `deploy/stop-local.ps1`로 끈다. 앱은 `http://localhost:3000`, API 문서는 `http://localhost:18000/docs`다. 두 포트는 loopback에만 열리며 DB 포트는 공개하지 않는다. 실제 AI API 키는 비워 두었다.

첫 화면의 프로젝트 생성 버튼이 존재하지 않는 주소로 이동하던 문제를 고쳐 기존 생성 창을 열도록 했다. 실제 Chromium에서 회원가입, 프로젝트 생성, 노드 생성과 실시간 반영, 같은 키의 생성 재요청을 확인했다. 컨테이너를 제거한 뒤 다시 생성하고 로그인해도 프로젝트와 노드가 보존됐다. 브라우저 JavaScript 오류는 없었고 세 컨테이너의 health check가 통과했다.

DB는 새 전용 볼륨 `brainnet-local_local-db`에 보존하며 기존 루트 Compose의 데이터는 수정하지 않았다. 최초 생성하는 `.env.local`은 비밀값이므로 Git에서 제외하고 볼륨과 함께 보관한다. [실행 안내](../deploy/README.md), [로컬 확인 결과](../experiments/runtime-nodes/results/performance-fix-2026-09-12/local-app.json).

## 반복 부하와 연속 검증

수정 후 행렬 24회는 완료했고 모든 회차가 오류율 1% 미만, DB 건수 일치, Outbox 잔여 0 기준을 통과했다. 646,820건 성공, 23건 실패이며 실패는 AI C300 두 번째 회차의 `503 NODE_CREATION_BUSY`다. 해당 회차 오류율은 0.5723%, AI C300 세 회차를 합친 오류율은 0.1908%다. 다른 23회는 무오류였다. 503도 성공으로 바꾸거나 재시도해서 집계하지 않았다.

| 요청 | 동시 요청 | FastAPI 성공 RPS | Spring 성공 RPS | FastAPI p95 | Spring p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 일반 | 100 | 126.63 | 947.39 | 984ms | 231ms |
| 일반 | 300 | 123.83 | 950.64 | 2,722ms | 822ms |
| AI | 100 | 62.67 | 454.49 | 2,064ms | 232ms |
| AI | 300 | 62.83 | 819.87 | 5,364ms | 545ms |

표는 회차별 지표의 중앙값이다. 요청 지연은 각 회차 안에서 4개 프로세스의 원본 요청을 합쳐 계산했다. 런타임 간 차이는 이 노드 생성 경로와 자원 설정에 한정하며 전체 서비스를 Spring으로 전환한 개선율이 아니다. 발생기 프로세스별 CPU 비율의 최댓값은 48.8%, loop 지연 p95 최댓값은 8.39ms, 프로세스 시작 편차 최댓값은 14.36ms였다. 종료 시 모든 검증 컨테이너에서 OOM·재시작이 없었다.

동시 실행 제한을 사실상 해제한 같은 이미지(`NODE_CREATE_CONCURRENCY=1000000`, `NODE_AI_CREATE_CONCURRENCY=1000000`)와 일반·AI C300을 각각 3회 비교했다. 발생기·DB·이미지·timeout·자원은 두 조건 모두 동일하며, 제한을 해제한 6회는 모두 시간 초과를 재현했다. 이는 이전 커밋 전체와의 비교가 아니라 이번 동시 실행 제한의 효과를 분리한 비교다.

| FastAPI C300 | 제한 해제 | 제한 적용 | 변화 |
| --- | ---: | ---: | ---: |
| 일반 성공 RPS | 106.84 | 123.83 | +15.9% |
| 일반 p95 | 10,002ms | 2,722ms | -72.8% |
| 일반 전체 오류율 | 6.2240% | 0% | 1,316건 → 0건 |
| AI 성공 RPS | 51.46 | 62.83 | +22.1% |
| AI p95 | 10,003ms | 5,364ms | -46.4% |
| AI 전체 오류율 | 11.1290% | 0.1908% | 1,241건 → 23건 |

RPS와 p95는 세 회차 중앙값, 전체 오류율은 세 회차의 실패 건수 / 전체 요청 수다. 제한 해제 조건의 실패는 10초 `ReadTimeout`, 제한 적용 후의 23건은 5초 대기 제한의 503이다. p95는 실패 요청도 포함하므로, timeout으로 잘린 값 이상의 완료 지연을 뜻하지 않는다.

엄격한 연속 검증을 3600.175초 실행했다. 논리 작업 18000개, WebSocket 100개, 전달 이벤트 3600000건을 대조했고 오류 0건, 접속자별 이벤트 누락 0건, 남은 노드 3개, 미발행 이벤트 0건이었다. 작업 p95는 247.82ms다. 재시도로 오류를 숨기지 않았으며 검증 중 컨테이너 OOM·재시작이 없었다. 이전 1시간 검증의 순간적인 실패 원인을 이번 결과만으로 특정하지는 않는다.

결과는 [원본 폴더](../experiments/runtime-nodes/results/performance-fix-2026-09-12/)와 [집계 JSON](../experiments/runtime-nodes/results/performance-fix-2026-09-12/summary.json)에 보존한다.

재집계: `python experiments/runtime-nodes/summarize_fix.py --require-complete`. 행렬 완료, 각 회차 오류율 1% 미만, DB 건수 일치, Outbox 잔여 0, 발생기 CPU·시작 편차·loop 지연, Spring p95 회귀 20% 이내, 엄격한 1시간 검증을 함께 확인한다. 조건이 미완료이거나 실패하면 명령이 실패한다.

[이전 실패 결과](REFACTORING_COMPLETION_2026-09-12.md), [실행·정리와 동시 처리 설정](../deploy/README.md), [측정 절차](../experiments/runtime-nodes/README.md).
