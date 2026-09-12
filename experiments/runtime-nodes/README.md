# 실제 프로젝트·노드 생성 구현 측정

`backend/`와 `spring/vertical-slice/`를 직접 실행해 비교한다. 축소 앱이나 언어 단독 벤치마크가 아니다.

## 실행 조건

- **전용 테스트 DB 필수.** `contract_seed.py`가 사용자·프로젝트·노드·멱등성·Outbox를 초기화한다.
- 두 서버에 동일한 JWT secret과 같은 Alembic-head PostgreSQL을 설정한다.
- 앱별 2 CPU·1 GiB, Spring heap 512MiB. FastAPI SQLAlchemy 최대 연결 30개, Spring Hikari 최대 30개다.
- 이벤트가 켜진 FastAPI worker는 publisher/listener용 PostgreSQL 연결 2개를 추가 사용한다.
- 실제 provider 호출은 기본 측정에 포함하지 않는다. `MODE=regular`가 기본값이다.

Python 의존성이 설치된 저장소 루트에서 다음 환경변수를 설정하고 실행한다.

```text
PYTHONPATH=backend
POSTGRES_URL=postgresql://<test-user>:<test-password>@<test-db>:5432/<test-db>
DATABASE_URL=postgresql+asyncpg://<test-user>:<test-password>@<test-db>:5432/<test-db>
JWT_SECRET=<both servers' test secret>
ALLOW_TEST_DATABASE_RESET=1
FASTAPI_BASE_URL=http://<fastapi>:8000
SPRING_BASE_URL=http://<spring>:8080
CONCURRENCY_LEVELS=10 100 300
DURATION_SECONDS=60
REPETITIONS=3
LOAD_PROCESSES=4
LOAD_CLIENT_POOL_SIZE=20
RESULTS_DIR=experiments/runtime-nodes/results/<run-name>
```

```bash
python experiments/runtime-nodes/load.py
```

각 회차 전에 데이터를 초기화하고 5초 warm-up을 수행한다. 홀수 회차는 FastAPI→Spring, 짝수는 Spring→FastAPI 순서로 실행한다. 요청별 새 멱등성 키, JWT 인증, 멤버십, 태그 상속, 원자적 Outbox 저장을 포함한다. 응답 성공 건수와 실제 DB 생성 행 수를 대조한다. 오류 응답을 포함한 p50/p95/p99와 성공 응답만의 p95를 구분한다. 1초 간격으로 DB 연결·대기 분류와 이벤트 상태를 저장하며 종료 뒤 미발행 0건까지 기다린 시간을 기록한다. 응답 지연과 처리량의 시간 분모는 monotonic clock을 사용한다.

부하 발생기는 기본 4개 프로세스로 총 동시 요청 수를 나눈다(300이면 각 75개). 각 프로세스의 HTTP 풀은 최대 20개 요청씩 맡는다. 단일 대형 httpcore 풀의 반복 탐색과 부하 발생기 한 코어 포화를 줄이기 위한 설정이며 서버 worker/CPU 수를 늘리는 설정이 아니다. 분할된 요청의 원본 지연을 합쳐 percentile을 계산하고, 가장 이른 시작부터 가장 늦은 완료까지를 처리량 분모로 쓴다. 프로세스별 최대 CPU 비율, 시작 시각 차이, event-loop 지연도 저장한다. 모니터 HTTP 오류는 해당 표본에 남기며 전체 측정 결과를 버리지 않는다.

이전 단일 풀·단일 프로세스 결과와 새 측정기의 RPS 차이를 앱 리팩터링의 순수 개선율로 해석하지 않는다. 앱 전후 비교에는 같은 측정기와 같은 자원 조건을 사용한다.

`MODE=ai`는 실제 애플리케이션의 HTTP provider 호출 경로를 실행한다. [전용 Compose](../../deploy/README.md)의 provider는 200ms 로컬 fixture이므로 실제 OpenAI의 지연·TLS·rate limit이나 생성 품질을 재현하는 것은 아니다. 두 모드 전체 행렬은 60초 × 3회 × 동시성 3개 × 런타임 2개 × 모드 2개, 총 36개 회차다.

`sample-resources.ps1`은 지정한 컨테이너의 Docker CPU·메모리 시계열을 기록한다. `load.py`의 `monitoring`은 DB 대기 이벤트별 연결 수이며 SQL별 대기시간 누적값은 아니다. WebSocket 100개와 1시간 생성·재시도·삭제 검증은 별도 `soak.py`로 실행한다.

`profile_fastapi.py`는 별도 포트(기본 8001)에 실제 FastAPI를 띄우고 서비스/provider/DB 메서드의 대기 포함 시간을 수집한다. `ALLOW_TEST_DATABASE_RESET=1`, `PYTHONPATH=backend`, 전용 DB 설정이 필요하다. 기본 60초 뒤 종료하며 `PROFILE_SECONDS`, `PROFILE_OUTPUT`으로 조절한다. 중첩 구간의 시간을 합산하지 않는다. `PROFILE_CREATION_CONCURRENCY`는 추가 제한의 진단용 옵션이며 운영 실행 경로에 포함되지 않는다. `soak.py`는 각 접속자의 이벤트 수와 오류 단계·키, 부하 발생기/provider fixture의 event-loop 지연을 기록한다.

`event_probe.py`는 별도로 FastAPI 두 인스턴스·Spring을 띄워야 한다. `contract_seed.py`와 `contract_probe.py` 뒤에 실행하며, DB 알림 listener를 강제로 종료한다. 운영 DB에서는 실행하지 않는다.

```text
JWT_TOKEN=<token returned by contract_seed.py>
FASTAPI_SECONDARY_URL=http://<second-fastapi>:8000
```

```bash
python spring/vertical-slice/event_probe.py
```

## 범위

`results/2026-09-12/`는 1차 구현의 C100 일반 생성 결과다. 후속 전체 행렬·연속 검증·브라우저 결과는 `results/final-2026-09-12/`에 별도로 보존한다. 후속 행렬에는 별도 DB에서 초당 5개 논리 작업과 WebSocket 100개를 실행하는 배경 부하가 있으며 PostgreSQL 서버와 호스트 자원을 공유한다. 전후 패치의 순수 효과나 운영 사용자 체감 개선율로 해석하지 않는다. 부하 중 브라우저 100개가 전체 노드를 재조회하는 비용은 포함하지 않는다.
