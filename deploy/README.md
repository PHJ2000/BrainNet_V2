# 전용 Docker에서 전환·롤백 검증

이 스택은 공개 배포 설정이 아닌 로컬 검증 환경이다. 테스트 계정과 DB를 사용하고, 호스트에는 `127.0.0.1:18080`(앱)과 `127.0.0.1:19090`(Prometheus)만 연다. 실제 AI 요금이 발생하지 않도록 200ms HTTP provider fixture를 사용한다. 기존 루트 Compose와 DB volume은 사용하지 않는다.

## 실행과 검증

저장소 루트에서 Docker를 켠 뒤 실행한다. E2E에는 Node 20과 PowerShell 7이 필요하다. `verify-local.ps1`, `contract_seed.py`, `load.py`는 이 스택의 `brainnet_test` 데이터를 초기화한다.

```powershell
docker compose -f deploy/local-validation.compose.yml build
docker compose -f deploy/local-validation.compose.yml up -d
cd frontend
npm ci
npx playwright install chromium
cd ..
# frontend의 production build 완료 후 실행
./deploy/verify-local.ps1
```

검증에는 두 런타임의 provider 429·timeout·잘못된 JSON·응답 유실, 두 FastAPI 인스턴스의 이벤트 전달과 연결 복구, 프로젝트별 proxy 전환·롤백, 실제 Chromium 두 화면의 동기화가 포함된다. 사용자 토큰은 환경변수로만 전달하며 출력하지 않는다. 브라우저는 테스트 seed 계정으로 접속한다.

프론트 API URL은 Next.js 빌드 시 `NEXT_PUBLIC_API_BASE_URL`로 고정한다. 이 구성의 값은 `http://localhost:18080`이다. 외부 배포에서는 서비스의 HTTPS 주소로 다시 빌드해야 한다.

## 한 프로젝트의 생성 요청 전환

```powershell
./deploy/set-canary.ps1 -ProjectIds 1
# 전체 생성 요청을 v1 계약의 FastAPI로 되돌림
./deploy/set-canary.ps1
```

일반·AI 생성은 모두 같은 `POST /projects/{id}/nodes` 규칙을 따른다. 허용 목록 밖 프로젝트, 읽기, 수정, 삭제, 투표, WebSocket은 FastAPI로 간다. Nginx 설정 검사 후 reload하며 `X-BrainNet-Writer`로 선택된 런타임을 확인한다. POST 자동 upstream 재시도는 끄고 클라이언트가 같은 멱등성 키로 재시도한다. `canary.map`의 저장소 기본값은 빈 목록이다.

기존 Spring hash와 새 fingerprint v1의 배포 호환 제약은 [요청 계약](../docs/migration/node-request-and-event-contract.md)을 따른다. 여기서 검증한 rollback은 **v1 지원 FastAPI로의 라우팅 복구**이며, 변경 전 바이너리·스키마로의 downgrade가 아니다.

## 관측과 보존

- `/health/events`: listener/publisher 준비 상태, 미발행 건수와 가장 오래된 지연, 프로세스별 실패·정리 누계.
- 내부 FastAPI `/metrics`: Prometheus가 15초 간격으로 수집한다. scrape 실패 1분, 이벤트 bridge 미준비 1분, 미발행 최장 지연 30초 초과가 2분 지속되면 경보를 계산한다. 외부 알림 수신자는 설정하지 않았다.
- 발행된 Outbox는 기본 7일 후, claim은 만료 1일 후 정리한다. 60초 간격, 트랜잭션당 각각 최대 1,000행이다. 미발행 Outbox와 유효 claim은 정리하지 않는다.
- proxy access log는 WebSocket token이 포함되는 query string을 기록하지 않는다.

## 한 시간 연속 검증

기능 테스트와 별도 DB를 사용하되 같은 PostgreSQL 서버를 공유한다. DB 생성은 새 스택에서 한 번 실행한다.

```powershell
docker compose -f deploy/local-validation.compose.yml exec -T db createdb -U brainnet_test brainnet_soak
docker compose -f deploy/local-validation.compose.yml --profile soak up -d soak-fastapi soak-spring
docker compose -f deploy/local-validation.compose.yml exec -T `
  -e POSTGRES_URL=postgresql://brainnet_test:brainnet_test@db:5432/brainnet_soak `
  -e DATABASE_URL=postgresql+asyncpg://brainnet_test:brainnet_test@db:5432/brainnet_soak `
  -e FASTAPI_BASE_URL=http://soak-fastapi:8000 -e SPRING_BASE_URL=http://soak-spring:8080 `
  -e SOAK_SECONDS=3600 -e RESULTS_DIR=experiments/runtime-nodes/results/soak `
  tools python experiments/runtime-nodes/soak.py
```

초당 5개 논리 작업(생성→반대 런타임 재시도→삭제), 그중 약 1/3 AI, WebSocket 100개를 유지한다. 최종 DB·멱등성·각 접속자 이벤트 수와 오류를 대조한다. 부하 행렬은 [측정 안내](../experiments/runtime-nodes/README.md)를 따른다. 같은 DB에서 seed·부하·기능 테스트를 동시에 실행하지 않는다.

## 정리

```powershell
# 이 검증 스택의 컨테이너·전용 테스트 volume만 제거
docker compose -f deploy/local-validation.compose.yml --profile soak down --volumes
```

운영 배포에는 별도의 비밀값, 실제 provider 설정, HTTPS 도메인, 지속 저장소, 외부 경보 수신자와 배포 권한이 필요하다. 이 로컬 구성의 테스트 비밀값을 외부 서비스에 사용하지 않는다.
