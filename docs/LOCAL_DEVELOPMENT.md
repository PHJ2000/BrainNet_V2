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

기본 Compose는 DB 영속 볼륨을 명시하지 않습니다. 컨테이너 제거·재생성 전에 필요한 DB 데이터를 백업하세요.

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
