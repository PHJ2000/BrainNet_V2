# 1단계 구현 및 검증 결과

2026-09-22, `C:\my_proj\BrainNet_V2`에서 수행. 1단계는 주간 계획의 1~3일차인 인증·초대·의존성·WebSocket 안정화다.

## 기준과 작업 범위

- 로컬 `feat/next-local-workflow`, HEAD `d98d145`; fetch한 `origin/main`은 `e60bad4`. 로컬은 원격 main을 포함하며 ahead 2 / behind 0이었다.
- 기존 미커밋 수정과 추가 파일을 보존했다. 초대 검증, 프로젝트 설정 UI, 그래프 hook 분리 등 이전 작업은 이번 신규 구현으로 계산하지 않았다.
- 이번 결과는 로컬 변경이다. 커밋·push·PR·원격 CI·배포는 수행하지 않았다.
- 개인 DB 대신 `brainnet-next-validation` Compose의 `brainnet_test`만 사용했다. 빈 스키마 왕복은 같은 전용 PostgreSQL의 별도 `brainnet_phase1_migration` DB에서 수행했다. Spring 통합 테스트는 Testcontainers가 만든 별도 임시 DB를 사용했다.

## 반영한 변경

| 영역 | 동작과 주요 파일 |
| --- | --- |
| 의존성 | FastAPI 0.141.1 / Starlette 1.6.0 및 잠금 의존성 갱신. `python-jose` 대신 PyJWT 사용. HS256의 기존 sub/exp 토큰 호환 검증. `pyproject.toml`, `poetry.lock`, `requirements.txt` 정합성 확인 |
| 인증 처리 | bcrypt를 동시 4개 작업 스레드로 제한하고 이벤트 루프에서 분리. 로그인 DB 연결은 비밀번호 검사 전에 반환. 없는 계정도 dummy hash 검사. 동시 가입은 DB UNIQUE와 rollback으로 201 한 건, 나머지 409 처리 |
| 입력·요청 제한 | 비밀번호 문자/UTF-8 바이트 길이, 이름·이메일 길이, 요청 본문·동시 처리·IP별 요청 횟수 제한. 429/Retry-After 및 화면 안내. 검증 오류의 input/ctx 제거 |
| 초대·CORS | 기존 계정 귀속·만료·일회성·재발급 초대 구현을 PostgreSQL에서 검증. 참여 token을 URL query에서 JSON 본문으로 이동. 허용 origin 목록 적용 |
| WebSocket | 만료된 JWT 종료, 멤버 권한/삭제 여부 재검사, 전체·사용자별 연결 수 제한, heartbeat/pong, 태스크·연결 정리. 브라우저 4401 재로그인 안내와 4403 그래프 숨김 |
| 로그 | Uvicorn access/error 기록에서 query token 값 제거. AccessFormatter가 사용하는 인자 구조를 보존하는 회귀 테스트 추가 |
| 공통 계약 | 삭제 프로젝트의 멤버 요청은 404, 비멤버는 403. Spring 노드 접근에서도 삭제 프로젝트 차단. 검증 오류의 input/ctx 제거를 Spring에도 적용하여 차등 계약 유지 |
| 검증 자동화 | 인증·WebSocket·실제 DB·브라우저 테스트 추가. Python lock/export 감사 CI 추가. 로컬 검증 스크립트에 실제 WebSocket 수명 probe 추가 |

## 이번 실행에서 통과한 검증

| 항목 | 결과 |
| --- | --- |
| 백엔드 전체 + 실제 PostgreSQL 회귀 | **145개 통과**. 동일 이메일 5개 동시 요청 중 계정 1개 생성 및 나머지 409, 잘못된 초대·타 계정·만료·재사용 거부, 삭제 프로젝트 접근 차단 포함 |
| Spring Testcontainers 통합 | **19개 통과**, 실패·오류·skip 0 |
| 프론트 단위 테스트 | **14개 통과** |
| 프론트 lint / production build | 통과. TypeScript 검증 포함 |
| Chromium E2E | **8개 통과**. 만료 안내·권한 종료·heartbeat, 두 브라우저 노드 변경, 응답 유실, 오프라인 복구, 이력 복구, 백업 다운로드/복원, 프로젝트 이동 포함 |
| FastAPI/Spring 차등 계약 | 통과. 공통 JWT, 오류·삭제 프로젝트, 버전 충돌, 양방향 멱등 응답, 100개 동시 writer 포함 |
| 이벤트 전달 | 두 FastAPI 인스턴스의 생성/수정/삭제/투표 수신, 중복 억제, listener 복구, 재연결 resync 통과 |
| 실제 WebSocket 수명 | 짧은 토큰 만료 **4401 / 1.44초**, 멤버 권한 삭제 **4403 / 10.01초**, 프로젝트 삭제 **4403 / 10.01초**. 별도 생성 fixture만 정리하는 네트워크 probe로 확인 |
| DB·컨테이너 재생성 | 이력·복원 receipt fingerprint 유지, 새 로그인과 복원 프로젝트 4개 노드 재조회 통과 |
| 빈 DB 마이그레이션 | upgrade head → downgrade 4c389bbebfad → upgrade head → alembic check 통과. 최종 b811001, drift 없음 |
| Python 잠금/감사 | Poetry check/export 일치. requirements의 운영·개발 패키지 감사에서 알려진 취약점 **0건** |
| 프론트 운영 의존성 감사 | `npm audit --omit=dev` **0건** |
| 정적 확인 | 수정한 인증 관련 Python Ruff, Git diff 공백 검사, 테스트 JWT를 주입한 root Compose 설정 검사 통과 |

브라우저의 만료·권한 종료 화면은 자동 assertion과 저장된 스크린샷을 모두 확인했다. `frontend/test-results/`에 `session-expired.png`, `access-revoked.png` 및 기존 기능 검증 이미지가 있다. 두 보안 화면 테스트는 브라우저 WebSocket 모킹으로 종료 코드 처리를 검증하고, 별도 실제 DB/네트워크 probe가 서버의 종료 코드를 검증한다.

첫 통합 실행에서 삭제 프로젝트 403/404 차이, Uvicorn 로그 필터의 인자 구조, 브라우저 alert 선택자 중복을 발견해 수정했다. 수정 후 위 검증은 통과했다.

## 재현

Docker Linux 엔진을 실행하고 저장소 루트에서 다음을 실행한다. 테스트용 DB와 포트 18080을 사용한다.

```powershell
./deploy/validate-next.ps1 -KeepRunning
```

이번 환경에는 저장소 내 `.tools/venv`에 Python/Poetry, `.tools/playwright`에 Chromium을 설치했다. 해당 브라우저를 재사용하려면 먼저 `$env:PLAYWRIGHT_BROWSERS_PATH="$PWD\.tools\playwright"`를 설정한다. `.tools`는 Git 로컬 exclude와 Docker context에서 제외했다.

실제 연결 수명만 다시 검증:

```powershell
docker compose -p brainnet-next-validation -f deploy/local-validation.compose.yml exec -T tools python backend/scripts/check_session_security.py
```

기록은 `deploy/validation-logs/brainnet-next-validation-20260922-141001.log`, `spring-phase1-tests.log`, `session-security.json`에 있다. Python 감사 JSON은 `.tools/dependency-audit.json`, 프론트 감사는 `.tools/frontend-runtime-audit.json`이다. 테스트 실행 후 검증용 Compose는 실행 상태로 남겨 두었다.

## 한계와 2단계 연결

- 요청·연결 수 제한은 프로세스별이다. 여러 replica의 공유 제한 및 trusted proxy 설정은 운영 환경에서 별도로 적용해야 한다.
- WebSocket 권한 변경은 주기적으로 감지한다. 정상 DB에서는 약 10초였으며 재검사 DB timeout은 5초다. 즉시 세션 폐기나 모든 기기 로그아웃 정책을 구현한 것은 아니다.
- WebSocket query token / localStorage 보관은 유지했다. 쿠키·접속 ticket 전환은 별도 설계가 필요하다. Uvicorn과 nginx access log 밖의 수집기까지 검증한 것은 아니다.
- Python·프론트 패키지 감사 0건은 전체 애플리케이션 보안 보증이 아니다. 이번에 Spring 의존성 전체 감사와 프론트 개발 의존성 감사는 수행하지 않았다.
- Pydantic 구식 config/from_orm, datetime.utcnow, TestClient 관련 deprecation 경고가 남아 있다. 이번 테스트의 실패 원인은 아니며 후속 정리 대상이다.
- 100개 writer 계약 테스트와 기존 1천 노드 E2E 측정은 대규모 운영 부하 인증이 아니다. 2단계의 고정 조건 전후 성능 측정은 아직 수행하지 않았다.
- 2단계는 오류/빈 화면 구분, 저장·연결 상태 및 재시도, 프로젝트 검색·정렬, 집중 리팩토링과 성능 측정이다.
