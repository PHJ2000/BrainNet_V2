# BrainNet 로컬 개발 안내

[프로젝트 README](../README.md)

## 빠른 실행

Git, Docker Engine 24 이상, Docker Compose v2가 필요합니다.

```bash
git clone https://github.com/PHJ2000/BrainNet_V2.git
cd BrainNet_V2
```

### 1. 환경변수 준비

이미 `.env`가 있다면 기존 파일을 사용하세요.

Bash에서는 다음 명령으로 예제를 복사합니다.

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env`의 `JWT_SECRET`에 무작위 비밀값을 넣습니다. 최소 32바이트가 필요합니다. 다음 중 사용 환경에 맞는 명령으로 생성한 값을 복사하세요.

Bash + OpenSSL:

```bash
openssl rand -hex 32
```

Windows PowerShell:

```powershell
$jwtBytes = New-Object byte[] 32
$jwtRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$jwtRng.GetBytes($jwtBytes)
$jwtRng.Dispose()
[BitConverter]::ToString($jwtBytes).Replace("-", "").ToLowerInvariant()
```

| 변수 | 설정 |
| --- | --- |
| `JWT_SECRET` | 필수. 위에서 생성한 값을 입력 |
| `OPENAI_API_KEY` | AI 생성 기능 사용 시 입력 |
| `OPENAI_MODEL` | 기본 `gpt-3.5-turbo`. 계정에서 사용 가능한 모델로 설정 |
| `OPENAI_TIMEOUT_SECONDS` | 기본 30초 |
| `REQUIRE_NODE_VERSION` | 기본 `false`. 노드 버전 검사 정책 |

AI를 제외한 기본 기능은 OpenAI 키 없이 시작할 수 있습니다. AI 호출에는 공급자 API 사용 비용이 발생할 수 있습니다. 전체 예제는 [.env.example](../.env.example)에 있습니다.

### 2. 시작과 확인

```bash
docker compose up --build -d
docker compose ps
```

| 대상 | 주소 |
| --- | --- |
| 웹 애플리케이션 | http://localhost:3000 |
| API 문서 | http://localhost:8000/docs |
| 상태 확인 | http://localhost:8000/health |
| PostgreSQL | localhost:5432 |

상태 확인 응답은 `{"status":"ok","service":"backend-legacy"}`입니다. PowerShell에서는 아래 `curl` 대신 `curl.exe`를 사용하세요.

```bash
curl http://localhost:8000/health
```

웹에서 회원가입·로그인 후 프로젝트를 생성하세요. AI 동작은 API 키를 설정한 후 확인합니다. 시작에 실패하면 `docker compose logs --tail=100 backend`로 DB 마이그레이션과 설정 오류를 확인하세요.

일시 중지와 재시작:

```bash
docker compose stop
docker compose start
```

기본 Compose는 `db-data` 명명 볼륨에 PostgreSQL 데이터를 저장합니다. `down`이나 컨테이너 재생성으로는 지워지지 않지만 `down -v`는 볼륨과 데이터를 삭제합니다. 영속 볼륨은 백업을 대신하지 않습니다.

### 기존 DB 볼륨 유지

기존 익명 볼륨이 있는 설치에서 새 설정만으로 `up`하면 빈 명명 볼륨을 사용하게 됩니다. 기존 데이터는 자동 이전되지 않습니다. 기존 DB 컨테이너를 지우기 **전에** 백업하고 아래 절차를 따르세요. 다른 저장소나 `deploy/local-app.compose.yml`의 DB에는 적용하지 않습니다.

```powershell
# 해당 설치의 기존 Compose 프로젝트/디렉터리에서 실행
$dbContainer = docker compose ps -a -q db
if (-not $dbContainer) { throw '기존 DB 컨테이너를 먼저 확인하세요.' }
docker inspect $dbContainer --format '{{range .Mounts}}{{println .Type .Name .Destination}}{{end}}'
```

출력에서 대상이 `/var/lib/postgresql/data`이고 종류가 `volume`인 기존 볼륨 이름을 확인합니다. `bind` 마운트라면 아래 절차 대신 원래 바인드 경로를 유지해야 합니다.

```powershell
$env:BRAINNET_DB_VOLUME = '위에서 확인한 기존 볼륨 이름'
docker volume inspect $env:BRAINNET_DB_VOLUME
docker compose -f docker-compose.yml -f deploy/existing-db.compose.yml config --quiet
docker compose -f docker-compose.yml -f deploy/existing-db.compose.yml up -d
```

기존 PostgreSQL 15 볼륨을 그대로 외부 볼륨으로 연결합니다. 한 볼륨에 두 DB 서버를 동시에 연결하지 마세요. 이후에도 **같은 환경 변수와 두 Compose 파일**을 함께 사용하세요. 설정을 저장하려면 로컬 `.env`에 `BRAINNET_DB_VOLUME`을 추가하고, 재기동 후 프로젝트 목록과 주요 데이터를 확인합니다. 이 변경 자체는 기존 컨테이너를 재시작하거나 볼륨을 수정하지 않습니다.

## API 사용

전체 경로와 요청·응답 스키마는 실행 중인 [Swagger UI](http://localhost:8000/docs)를 기준으로 확인합니다.

| 요청 | 입력 형식 | 인증 |
| --- | --- | --- |
| `POST /auth/register` | JSON: 이메일·이름·비밀번호 | 불필요 |
| `POST /auth/login` | form-urlencoded: `username`에 이메일, `password`에 비밀번호 | 불필요 |
| 보호된 프로젝트·노드 API | 경로별 스키마 참고 | `Authorization: Bearer <token>` |

회원가입 후 로그인 요청 예시:

```bash
curl -X POST http://localhost:8000/auth/login --data-urlencode "username=you@example.com" --data-urlencode "password=your-password"
```

응답의 `access_token`을 Swagger의 Authorize 또는 Bearer 헤더에 사용합니다. 노드 수정에는 `expected_version` 계약이 있으며 관련 구현은 [노드 라우터](../backend/app/routers/nodes.py), 회귀 검증은 [테스트 폴더](../backend/tests)에 있습니다.

## 인증 및 WebSocket 설정

- `CORS_ALLOWED_ORIGINS`는 쉼표로 구분한 브라우저 origin입니다. 기본값은 `http://localhost:3000,http://localhost:18080`입니다. WebSocket의 Origin 검증에도 사용합니다.
- 회원가입 비밀번호는 8자 이상, UTF-8 72바이트 이하이며 NUL 문자를 허용하지 않습니다. 이름은 80자, 이메일은 120자 이하입니다. 기존 짧은 비밀번호의 로그인은 유지합니다.
- `POST /projects/join`은 JSON `{ "token": "초대 코드" }`를 받습니다. 예전 query 방식은 지원하지 않습니다.
- 로그인·가입·초대 참여에는 프로세스별 IP당 분당 60회, 동시 요청 32개, 본문 16KiB 제한을 적용합니다. `.env.example`의 `AUTH_*`로 조정하며 초과 시 429와 `Retry-After`를 반환합니다. bcrypt 작업 스레드는 프로세스당 4개입니다.
- WebSocket은 기본 10초마다 멤버십·프로젝트 삭제 여부를 재검사하고 heartbeat `{"type":"ping"}`을 전송합니다. 클라이언트는 텍스트 `pong`으로 응답해야 합니다. 4401은 인증 만료, 4403은 권한 종료, 4408은 heartbeat 응답 없음입니다. 연결 수는 프로세스 전체 512개, 사용자당 8개입니다.
- IP 제한과 연결 수 제한은 여러 서버 사이에 공유되지 않습니다. 프록시 사용 시 ASGI가 인식하는 주소가 제한 기준입니다. 운영에서는 신뢰하는 프록시 주소를 명시하고 ingress에서 공통 제한을 적용해야 합니다. 임의의 `X-Forwarded-For`를 앱이 직접 신뢰하지 않습니다.
- WebSocket query token은 현재 유지합니다. Uvicorn 로그에서 값을 숨기며 nginx access log는 query를 제외합니다. 다른 프록시·APM 로그도 별도 설정이 필요합니다. HttpOnly 쿠키/일회용 접속 ticket 전환은 후속 범위입니다.

의존성을 변경하면 `poetry lock` 후 `poetry export --with dev --without-hashes -o requirements.txt`로 내보냅니다. CI는 lock/export 일치와 Python 의존성 감사를 실행합니다.

1단계의 실행 결과와 재현 명령은 [검증 보고서](PHASE1_RESULT_2026-09-22.md)를 참고하세요.
