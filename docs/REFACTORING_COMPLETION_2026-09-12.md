# BrainNet V2 최종 구현·검증 결과

2026-09-12 · 기준 `be75d7a` · [PR #6](https://github.com/PHJ2000/BrainNet_V2/pull/6)

**요청 중복 방지, 이벤트 전달, 책임별 코드 분리와 로컬 전환·롤백을 구현했다. 기능 CI는 통과했지만 고부하 운영 확대 기준은 충족하지 못했다.** 지정 프로젝트의 일반·AI 생성을 함께 Spring으로 보내고 v1 FastAPI로 되돌리는 동작은 검증했다. 저장소의 canary 목록은 빈 상태로 유지한다.

## 구현과 기능 검증

| 변경 | 결과 |
| --- | --- |
| FastAPI/Spring 요청 계약 통일 | UTF-8 fingerprint v1, 사용자·키 단위 충돌 검사, 처리 lease, 완료 응답 24시간 재사용. 같은 요청을 두 런타임에 동시에 보내도 생성 1건 |
| 프론트 요청 재시도 | 사용자 동작별 키, 응답 유실 때 같은 키, AI 일부 성공 시 완료 슬롯 유지, 불확실한 실패에는 임의 fallback 생성 안 함 |
| 노드 수정 계약 | 기본 `expected_version` 필수. 누락 428, 오래된 버전 409 |
| 이벤트 원자성·여러 인스턴스 전달 | 생성·수정·삭제·활성 변경·투표 이벤트를 변경 트랜잭션에 저장. PostgreSQL 알림으로 각 FastAPI worker의 WebSocket에 전달, 연결 복구 시 DB 재조회 |
| 책임 분리 | Python HTTP 라우터·노드 서비스·provider·멱등성·Outbox, Java provider·멱등성·Outbox, 프론트 재시도·미완료 생성 계획·이벤트 구독 분리 |
| 추가로 발견한 결함 | 존재하지 않는 투표 컬럼 참조, 문자열 timestamp, 동시 투표·확정 중복 처리 수정. Java parent 잠금 후 존재 확인 및 AI 응답 파싱 정렬 |
| provider 전송 | 로컬 HTTP fixture의 429, timeout, malformed/empty 응답, 클라이언트 응답 유실 검증. Java cleartext HTTP/2 upgrade 문제를 HTTP/1.1로 해결 |
| 보존·관측 | 발행 Outbox 기본 7일, claim 만료 후 1일, 배치 정리. `/health/events`, Prometheus 수집과 경보 규칙 3개 |
| 프론트 의존성 | Next 16.3.5와 의존성 갱신, ESLint CLI 전환, 비밀번호 콘솔 출력 제거. 당시 `npm audit` 전체 0건 |

Python **51개**, Java **19개**, 프론트 단위 **7개**, Chromium E2E **1개**가 통과했다. 일반 테스트 합계는 기존 56개에서 78개로 늘었으나 코드 커버리지 증가율을 뜻하지 않는다. production build, Alembic upgrade/check/downgrade round-trip, 실제 HTTP differential probe, 두 인스턴스 이벤트 복구, 프로젝트별 canary·rollback도 실행했다.

원격 CI는 backend, frontend, Spring, browser/provider/rollout 네 job을 모두 통과했다. [검증 실행](https://github.com/PHJ2000/BrainNet_V2/actions/runs/34678780435). 첫 CI의 브라우저 기능 검증은 끝까지 진행됐지만 스크린샷 저장 권한 때문에 실패했다. 캡처를 Playwright의 `testInfo.outputPath`에 저장하도록 수정한 뒤 재실행했다. 이는 브라우저 테스트를 생략한 처리가 아니다.

## 실제 앱 부하 비교

FastAPI와 Spring **둘 다 이번 요청 계약을 구현한 버전**이다. 언어만 바꾸기 전후의 순수 효과나 서비스 전체 개선율이 아니다. 앱별 2 CPU·1 GiB, 최대 DB 연결 30개, PostgreSQL 15, 5초 warm-up 후 **60초 × 3회**, 동시 요청 **10·100·300**, 일반·AI 모드를 측정했다. AI는 **200ms 로컬 HTTP fixture**이고 실제 OpenAI가 아니다.

일반 C10/C100은 별도 DB의 초당 5개 논리 작업·WebSocket 100개와 같은 PostgreSQL/호스트를 공유했다(`matrix`). 일반 C300 및 AI 전체는 연속 검증을 끝낸 뒤 측정했다(`isolated`). 따라서 서로 다른 부하 수준의 숫자를 연결해 확장성을 단정하지 않는다. 아래는 **회차별 지표의 중앙값**이며 모든 응답을 합친 지연 분포가 아니다.

| 모드·동시성 | FastAPI 성공 RPS | Spring 성공 RPS | FastAPI p95 | Spring p95 | Spring 처리량 비율 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 일반 10 | 40.528 | 182.528 | 370.262ms | 103.785ms | 4.504배 |
| 일반 100 | 154.139 | 323.111 | 1,754.967ms | 962.843ms | **2.096배** |
| 일반 300 | 100.929 | 200.149 | 9,973.823ms | 5,173.172ms | 1.983배 |
| AI 10 | 39.268 | 46.416 | 302.623ms | 220.664ms | 1.182배 |
| AI 100 | 55.004 | 66.818 | 4,202.333ms | 5,314.513ms | 1.215배 |
| AI 300 | 41.795 | 59.766 | 10,007.227ms | 13,532.866ms | 1.430배 |

일반 C100에서는 **처리량 +109.6%, p95 45.1% 감소**였다. 그러나 C10 FastAPI 회차는 약 31~158 RPS로 편차가 커서 4.5배를 대표 개선율로 사용하지 않는다. AI C100/C300에서는 Spring의 p95가 각각 **26.5%·35.2% 길어져** 초안의 20% 이내 회귀 기준을 넘었다. C300 FastAPI의 시간 초과는 지연 분포를 잘라내므로 짧은 p95만으로 유리하다고 판단할 수 없다.

36개 정규 회차의 합계는 **성공 248,204건, 실패 2,320건**이다. 일반 C10/C100 및 Spring 일반 C300은 오류 0건. FastAPI 일반 C300은 813건, AI C100은 6건, AI C300은 1,499건 실패했고 Spring AI C300도 2건 실패했다. FastAPI C300 오류율 중앙값은 일반 약 4.2%, AI 약 15.9%로 1% 기준을 넘었다.

`matrix`의 최초 C300 실패 회차는 위 36개 합계와 별도로 보존했다. 4,885건 중 1,069건이 시간 초과였고 측정기가 성공 응답 수와 DB 행 수 불일치에서 중단됐다. HTTP 시간 초과가 발생해도 서버는 commit할 수 있으므로, 측정기를 수정해 미확정 claim 종료를 기다리고 **성공 응답 + 시간 초과 후 commit**과 DB 행 수를 대조한다. 실패율 기준은 완화하지 않았으며 실패 회차도 JSON을 쓴 뒤 나머지 조건을 측정한다.

수정한 측정기로 실행한 24개 `isolated` 회차는 모두 DB 증가 건수가 확인된 결과와 일치했고 Outbox도 0건까지 비워졌다. 이전 정상 12개 회차도 성공 응답과 DB 증가 건수가 일치했다. DB 연결·대기 종류는 1초 간격으로 저장했다. 이는 SQL별 대기시간 누계가 아니다. CPU·컨테이너 메모리는 최초 행렬·1시간 검증에만 시계열이 있고, 후속 격리 회차에는 연속 자원 표본이 없다.

원본: [최종 결과 폴더](../experiments/runtime-nodes/results/final-2026-09-12/), [재집계 JSON](../experiments/runtime-nodes/results/final-2026-09-12/summary.json). 재집계: `python experiments/runtime-nodes/summarize.py`. 1차 구현 당시의 C100 1.909배 수치는 [이전 보고서](REFACTORING_RESULT_2026-09-12.md)에 별도 보존했다.

추가로 FastAPI의 `pool_size=10, max_overflow=20`을 `30, 0`으로 바꾸어 최대 연결 수는 유지하고 초과 연결 생성·폐기를 줄이는 후보를 C300 일반·AI 각각 3회 시험했다. 일반 생성은 악화됐고 AI도 오류율 목표에 미달해 **최종 코드에 채택하지 않고 되돌렸다**. 이 6개 회차는 `pool-reuse`에 보존했으며 위 36개 합계에서 제외했다. 초과 연결의 반환 시 폐기 동작은 [SQLAlchemy 공식 문서](https://docs.sqlalchemy.org/en/20/core/pooling.html#sqlalchemy.pool.QueuePool.__init__)를 따른다.

## 1시간 연속 검증과 복구

실제 런타임 두 개, WebSocket 100개, 초당 5개 논리 작업(생성→반대 런타임 재시도→삭제), 약 1/3 AI로 **3,600초** 실행했다. **18,000개 중 17,994개 완료**, HTTP read timeout 2건과 provider timeout 4건이 발생했으므로 무오류 기준은 **실패**다. OOM과 컨테이너 자동 재시작은 없었다. 개별 timeout의 정확한 원인은 이 실행의 로그만으로 확정하지 못했다.

완료 작업의 p95는 285.4ms, 생성 시작부터 첫 관측자 이벤트 수신까지 p95는 462.3ms였다. DB에는 생성 이벤트 17,995개와 삭제 이벤트 17,994개가 저장됐고, 관측한 이벤트 총 3,598,900건은 두 종류의 DB 이벤트 합계 × 100과 일치했다. 이는 aggregate 대조이며, 이벤트별·접속자별 완전 무중복 증명으로 확대하지 않는다. 미발행은 0건이었다.

시간 초과 뒤 남은 노드 1개를 기존 claim의 키로 **FastAPI와 Spring 각각에 재요청**해 같은 응답을 받았고, 노드·이벤트가 추가되지 않았다. 그 노드를 삭제한 뒤 seed 노드 3개, 미완료 claim 0개, 미발행 0개를 확인했다. [복구 증거](../experiments/runtime-nodes/results/final-2026-09-12/soak-verified/recovery.json). 이 복구 성공은 1시간 무오류 테스트의 실패를 통과로 바꾸지 않는다.

## 다음 개선과 전환 판단

1. **AI 고부하부터 계측한다.** HTTP client 대기·provider 처리·DB checkout/commit 구간을 구분해 지연 원인을 찾고, 서비스의 허용 동시 AI 요청 수와 절대 응답시간 목표를 정한다. 필요하면 명시적 작업 대기열과 진행 상태 조회를 도입한다. 단순히 timeout을 늘려 오류를 숨기지 않는다.
2. **같은 호스트에서 조건을 겹치지 않고 반복한다.** 실제 provider 계정·staging이 마련되면 TLS·rate limit·취소·비용을 포함하고, 설정 확정 뒤 1시간 무오류 기준을 다시 검증한다. 현재 1시간 결과는 실패로 유지한다.
3. **운영 확대는 보류한다.** 로컬 전환·rollback 기능은 통과했지만 AI p95와 FastAPI rollback 경로의 C300 오류 기준이 충족되지 않았다. 실제 운영 도메인·provider 키·외부 경보 수신자가 제공되지 않아 외부 배포와 실제 AI 호출은 수행하지 않았다.

이벤트는 DB 재조회에 의한 최종 상태 복구 계약이며 과거 모든 이벤트 재생은 보장하지 않는다. 프론트 미완료 생성 계획은 현재 화면 메모리에 있으므로 새로고침까지 지속되지 않는다. [요청·이벤트 계약](migration/node-request-and-event-contract.md), [전용 Docker 실행·정리](../deploy/README.md).
