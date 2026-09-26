# BRAINNET

AI로 아이디어를 확장하고 마인드맵으로 정리하는 웹 애플리케이션입니다. 프로젝트별로 주제를 입력하고, AI 추천이나 직접 작성한 아이디어를 연결하며, 태그로 분류하고 이미지로 내보낼 수 있습니다.

```text
회원가입·로그인 → 프로젝트 생성 → 주제 입력 → 아이디어 확장 → 태그 분류·PNG 내보내기
```

## 현재 구현 범위

| 기능 | 현재 동작 |
| --- | --- |
| 계정·프로젝트 | 회원가입, JWT 로그인, 프로젝트 생성·목록·상세 화면 |
| 마인드맵 | 노드 내용 수정, 드래그 이동, 확대·축소, 변경사항 DB 저장 |
| AI 확장 | 루트에서 AI 추천 2개 + 직접 입력용 1개, 하위 확장에서 AI 추천 1개 + 직접 입력용 1개 생성 |
| 태그 | 노드 우클릭으로 태그 생성·부착·제거, `TAG` 버튼으로 강조 표시 |
| 이미지 내보내기 | `SAVE` 버튼으로 `graph.png` 다운로드 |
| 실시간 갱신 | WebSocket 이벤트를 받으면 노드를 다시 조회하고, 재연결·주기적 조회로 상태 복구 |
| 요청 안정성 | 생성 재시도의 중복 방지, 버전 기반 수정 충돌 감지, 일반·AI 생성의 별도 동시 실행 제한 |

개인 브레인스토밍 사용을 중심으로 구현되어 있습니다. WebSocket과 프로젝트 멤버십 코드는 있지만 완성된 다중 사용자 협업 서비스는 아닙니다. 초대 API는 토큰 저장·메일 발송이 생략되어 있고, 참여 API는 프로젝트 ID가 `1`로 고정된 예시 구현입니다.

히스토리·투표 조회 및 처리 API도 있지만, 현재 웹 화면에는 히스토리 복원이나 투표 UI가 없습니다. 히스토리를 마인드맵 전체 스냅샷의 되돌리기 기능으로 설명하지 않습니다.

## 구성

```text
브라우저: Next.js + React + Cytoscape.js
    │ REST / WebSocket
    ▼
FastAPI ── AI 요청 ── OpenAI API
    │
    ▼
PostgreSQL 15
```

- **프론트엔드:** Next.js, React, TypeScript, Tailwind CSS, Cytoscape.js, TanStack Query.
- **백엔드:** Python, FastAPI, SQLAlchemy, Alembic, JWT 인증.
- **데이터베이스:** PostgreSQL 15. 백엔드 시작 시 DB 준비를 기다리고 `alembic upgrade head`를 실행합니다.
- **Spring:** `spring/vertical-slice`에 Java 25 기반의 일부 API 구현이 있습니다. 런타임 비교와 점진적 전환 검증용이며, 평소 로컬 앱은 FastAPI를 사용합니다.

기존 소개 다이어그램과 ERD는 다음과 같습니다. 이후 추가된 요청·이벤트 계약은 [별도 문서](docs/migration/node-request-and-event-contract.md)를 기준으로 확인합니다.

![프로젝트 소개 다이어그램](images/diagram.png)
![ERD](images/ERD.png)

## 실행 방식 선택

Docker와 Docker Compose v2 이상이 필요합니다. 두 앱 구성 모두 프론트 포트 `3000`을 사용하므로 동시에 실행하지 않습니다.

| 구성 | 용도 | 앱 / API 문서 | AI 설정 |
| --- | --- | --- | --- |
| `deploy/local-app.compose.yml` | 평소 로컬 사용, production 프론트 빌드, 전용 DB 영속 볼륨 | `3000` / `18000/docs` | 빈 키로 고정 |
| 루트 `docker-compose.yml` | 개발 서버, 소스 변경 반영, 실제 AI 연결 | `3000` / `8000/docs` | `.env`의 키 사용 |
| `deploy/local-validation.compose.yml` | Spring 전환·롤백, E2E, 부하 검증 | `18080` / 별도 검증 구성 | 로컬 모의 provider |

처음 내려받는 경우:

```bash
git clone https://github.com/PHJ2000/BrainNet_V2.git
cd BrainNet_V2
```

### 1. 평소 사용할 로컬 앱

이 구성은 앱과 API를 `127.0.0.1`에만 열고 DB 포트는 호스트에 공개하지 않습니다. 프론트 production 빌드와 각 서비스의 health check를 사용합니다.

**PowerShell 7**에서는 저장소 루트에서 실행합니다.

```powershell
./deploy/start-local.ps1

# 이미지를 다시 빌드하지 않고 시작
./deploy/start-local.ps1 -NoBuild

# 중지: DB 데이터 유지
./deploy/stop-local.ps1
```

**Linux / Bash**에서는 같은 구성을 다음과 같이 실행할 수 있습니다. 비밀값 생성에는 `openssl`이 필요합니다.

```bash
# 최초 한 번만 생성. 기존 .env.local은 덮어쓰지 않습니다.
if [ ! -f .env.local ]; then
  (
    umask 077
    printf 'JWT_SECRET=%s\nBRAINNET_LOCAL_DB_PASSWORD=%s\n' \
      "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" > .env.local
  )
fi

docker compose -p brainnet-local --env-file .env.local \
  -f deploy/local-app.compose.yml up --build -d --wait --wait-timeout 180

# 상태 확인
docker compose -p brainnet-local --env-file .env.local \
  -f deploy/local-app.compose.yml ps

# 중지: DB 데이터 유지
docker compose -p brainnet-local --env-file .env.local \
  -f deploy/local-app.compose.yml stop
```

다음 실행에서는 `up` 명령의 `--build`를 생략할 수 있습니다.

- 앱: <http://localhost:3000>
- API 문서: <http://localhost:18000/docs>
- DB 데이터: `brainnet-local_local-db` 볼륨에 보존됩니다.
- `.env.local`은 DB 비밀번호와 JWT 비밀값을 담고 있으므로 볼륨과 함께 보관합니다. Git에는 포함되지 않습니다.

**이 구성은 AI API 키를 빈 값으로 고정합니다.** `.env.local`에 키만 추가해도 활성화되지 않습니다. 키가 없으면 AI 추천 자리는 직접 입력할 수 있는 `?` 노드로 대체됩니다. 실제 AI를 연결하려면 아래 개발 구성을 사용합니다.

### 2. 개발 및 실제 AI 연결

저장소 루트에서 실행합니다. 아래 환경파일 준비 명령은 Bash 기준이며 기존 `.env`를 보존합니다.

```bash
if [ ! -f .env ]; then
  cp .env.example .env
  JWT_SECRET_VALUE="$(openssl rand -hex 32)"
  sed -i "s/^JWT_SECRET=.*/JWT_SECRET=${JWT_SECRET_VALUE}/" .env
fi
```

기존 `.env`를 사용한다면 `JWT_SECRET`이 설정되어 있는지 확인합니다. 최소 32바이트가 아니면 백엔드가 시작되지 않습니다.

실제 AI 추천을 사용하려면 `.env`를 편집합니다.

```dotenv
OPENAI_API_KEY=본인의_API_키
OPENAI_MODEL=gpt-3.5-turbo
OPENAI_TIMEOUT_SECONDS=30
```

`OPENAI_MODEL`은 저장소 기본값입니다. 연결하는 계정에서 사용할 모델에 맞춰 변경할 수 있습니다. 실제 API 호출에는 사용 요금이 발생할 수 있습니다. 키 없이도 직접 입력과 일반 마인드맵 기능을 사용할 수 있습니다.

```bash
# 빌드 및 실행
docker compose up --build -d

# 상태 및 로그 확인
docker compose ps
docker compose logs --tail=100 backend frontend

# 중지 / 재시작
docker compose stop
docker compose start
```

- 앱: <http://localhost:3000>
- API 문서: <http://localhost:8000/docs>
- DB: `localhost:5432`

루트 Compose의 프론트는 `npm run dev`로 실행되며 소스 디렉터리를 연결합니다. 이 구성은 고정된 개발용 DB 계정과 호스트 공개 포트를 사용하고, DB의 명시적 이름 있는 볼륨을 정의하지 않습니다. 지속적인 로컬 데이터 보관에는 앞의 로컬 앱 구성을 사용합니다. `down -v`는 볼륨까지 제거하므로 데이터 보존용 중지 명령으로 사용하지 않습니다.

### 프론트엔드 개별 빌드

Docker 밖에서 프론트만 개발하거나 빌드를 확인하려면 Node.js 20 기준으로 실행합니다. 명령은 루트가 아닌 `frontend` 디렉터리에서 실행합니다.

```bash
cd frontend
npm ci

# 개발 서버: 별도 실행한 백엔드 필요
npm run dev

# production 빌드 및 실행
npm run build
npm start
```

API 기본 주소는 `http://localhost:8000`입니다. 다른 백엔드 주소를 사용한다면 `NEXT_PUBLIC_API_BASE_URL`을 설정합니다. production 빌드에는 이 값이 빌드 시 반영되므로, 주소를 바꾸면 다시 빌드해야 합니다. 예를 들어 로컬 앱의 API에 연결하는 빌드는 다음과 같습니다.

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:18000 npm run build
```

## 화면 사용법

1. 앱에서 **회원가입 → 로그인**합니다.
2. **새 프로젝트 만들기** 또는 왼쪽 **새 프로젝트** 버튼으로 이름과 설명을 입력합니다.
3. 왼쪽 **내 프로젝트** 목록에서 만든 프로젝트를 엽니다.
4. 가운데 **주제를 입력하세요** 노드를 클릭하고 주제를 입력합니다. 첫 확장에서 주변에 추천·직접 입력용 노드가 생깁니다.
5. 흐리게 표시된 AI 추천 노드는 클릭하면 활성화됩니다. `?` 노드는 클릭해서 내용을 입력하면 활성화되고 하위 아이디어를 생성합니다. 활성 노드는 클릭해서 내용을 수정할 수 있으며, 아직 확장하지 않은 노드는 내용 수정 시 하위 아이디어를 생성합니다.
6. 노드를 드래그해서 배치합니다. 노드 우클릭으로 태그를 붙이거나 제거하고, **TAG** 버튼에서 특정 태그를 강조합니다.
7. **SAVE** 버튼으로 마인드맵을 PNG 이미지로 내려받습니다.

노드 내용과 위치 변경은 API를 통해 DB에 저장합니다. **SAVE는 DB 저장 버튼이 아니라 이미지 내보내기 버튼**입니다. AI provider 미설정이나 명시적인 provider 실패 시에는 빈 노드 입력으로 대체합니다. 서버 과부하 응답은 같은 생성 키로 재시도하며 빈 노드 생성으로 대체하지 않습니다.

## API 및 개발 문서

전체 요청·응답 스키마는 실행 중인 백엔드의 `/docs`에서 확인합니다. 보호된 API에는 `Authorization: Bearer <token>`이 필요합니다. 회원가입·로그인은 토큰 없이 호출하며, 로그인은 JSON이 아닌 `application/x-www-form-urlencoded` 형식의 `username`(이메일)과 `password`를 받습니다.

| 영역 | 주요 경로 |
| --- | --- |
| 인증 | `POST /auth/register`, `POST /auth/login` |
| 사용자 | `GET /users/me`, `GET /users/me/tag-summaries` |
| 프로젝트 | `/projects`, `/projects/{project_id}` |
| 노드 | `/projects/{project_id}/nodes`, `/projects/{project_id}/nodes/{node_id}` |
| 노드 활성화 | `POST /projects/{project_id}/nodes/{node_id}/activate`, `/deactivate` |
| 태그 | `/projects/{project_id}/tags` |
| 투표·히스토리 | `/projects/{project_id}/tags/{tag_id}/vote`, `/projects/{project_id}/votes/confirm`, `/projects/{project_id}/history` |
| 실시간 이벤트 | `WS /projects/{project_id}/ws?token=...` |
| 상태 확인 | `GET /health`, `GET /health/events`, `GET /metrics` |

노드 생성 재시도에는 같은 `Idempotency-Key`를 사용하고, 수정에는 `expected_version`을 전달합니다. 상세 동작과 오류 응답은 [노드 요청·이벤트 계약](docs/migration/node-request-and-event-contract.md)을 참고합니다.

## 검증 상태

저장소의 [2026-09-12 후속 수정 보고서](docs/PERFORMANCE_FIX_2026-09-12.md)에는 다음 결과가 기록되어 있습니다. 이는 해당 시점의 검증 기록이며, 새 환경에서의 실행 성공을 보장하는 결과는 아닙니다.

- Python 57개, 프론트 단위 8개, Spring 19개, Chromium E2E 1개: 총 85개 테스트 통과.
- 프론트 build/lint, DB 마이그레이션, 런타임 간 API 계약, 이벤트 복구, 전환·롤백 검증 통과.
- 후속 1시간 연속 검증에서 논리 작업 18,000개, WebSocket 100개, 오류·접속자별 이벤트 누락 0건.
- AI 부하 검증은 로컬 모의 provider를 사용했으며, 실제 OpenAI 호출의 품질·요금·rate limit 검증은 포함하지 않음.

프론트의 기본 검증 명령:

```bash
cd frontend
npm run build
npm run lint
npm test
```

백엔드·Spring·브라우저 통합 검증은 별도 DB와 환경변수가 필요합니다. [CI 설정](.github/workflows/ci.yml), [Docker 검증 절차](deploy/README.md), [부하 측정 안내](experiments/runtime-nodes/README.md)를 참고합니다. 검증 스크립트 일부는 테스트 데이터를 초기화하므로 평소 쓰는 DB에 연결하지 않습니다.

전환 시 서비스 롤백은 v1 계약을 지원하는 FastAPI로 라우팅을 되돌리고 확장된 DB 스키마를 유지하는 방식입니다. 데이터가 있는 환경에서 Alembic downgrade를 실행하면 version·idempotency·outbox 데이터가 삭제되므로 사용하지 않습니다.

## 디렉터리

```text
backend/                 FastAPI 앱, Alembic 마이그레이션, Python 테스트
frontend/                Next.js 화면, 그래프, 프론트 단위·E2E 테스트
spring/vertical-slice/   Java 25 / Spring 일부 API 및 비교 검증
deploy/                  로컬 앱·검증 Compose, 실행 스크립트, 라우팅·모니터링
docs/                    설계 결정, 요청·이벤트 계약, 리팩터링·성능 보고서
experiments/             provider·런타임 비교, 부하·연속 검증 및 결과
images/                  소개 다이어그램, ERD
```

## 팀

| 이름 | 담당 |
| --- | --- |
| 김동건 | 팀 리더, 프론트엔드, AI |
| 박재홍 | 백엔드, 아키텍처, FastAPI·PostgreSQL |
| 이승재 | 백엔드·프론트엔드, API, 실행 환경, Next.js·Cytoscape.js |

라이선스: MIT License.

문의: [koreaworldclass@gmail.com](mailto:koreaworldclass@gmail.com) 또는 GitHub Issues.
