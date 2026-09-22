# 6개 후속 개선 결과 — 2026-09-22

기준 커밋 `63c0534`, 작업 브랜치 `feat/next-local-workflow`. BrainNet_V2 폴더에서 작업했으며 기본 배포는 Next.js + FastAPI + PostgreSQL이다.

## 완료 범위

| 항목 | 구현과 확인 |
| --- | --- |
| 1. 노드 편집·초안 | 여러 줄 편집창, 닫기·새로고침 후 이어쓰기, 계정·프로젝트·탭별 초안, 요청 키 유지, 저장 실패 재시도와 충돌 시 서버 내용 비교 |
| 2. 태그 오류 | 실패 내용과 재시도 표시, 재시도 전 서버 상태 재조회로 이미 반영된 연결·해제를 중복 실행하지 않음 |
| 3. 수동 작성·AI 분리 | 저장은 AI를 호출하지 않음. 별도 AI 생성 메뉴와 오류 상태, 키 없는 기본 로컬 배포의 수동 작성 안내 |
| 4. 협업 권한 | 멤버 목록·EDITOR/VIEWER 변경·내보내기·초대 철회·VIEWER 초대. 소유자 강등/제거 거부. FastAPI와 Spring의 쓰기 API에서 VIEWER 차단 |
| 5. 큰 그래프 | 검색 결과 없음 전환 시 노드별 스타일 재계산 생략. ETag가 같으면 304와 빈 본문으로 응답하고 태그 재다운로드 생략. 연결 정상 시 보정 조회는 120초, 단절 시 30초, 탭 복귀 시 즉시 재조회 |
| 6. 장애·메모리 진단 | 세 탭에서 12회 UI 편집, 동시 버전 충돌, 연결 중단, API 2개 재시작, 같은 생성 요청 재전송, 세 탭 새로고침 후 데이터 유지 확인 |

VIEWER는 노드·태그·투표·되돌리기 쓰기를 할 수 없다. 멤버 관리는 OWNER만 가능하며 초대 목록은 토큰을 노출하지 않는다. `b822001` 마이그레이션은 기존 멤버의 역할을 변경하지 않는다. VIEWER 데이터가 남아 있는 상태의 downgrade는 명시적으로 거부한다.

## 검증

- 백엔드 회귀 148개: 최초 146개 통과, 추가 테스트 2개의 예약 도메인 이메일 데이터를 수정한 뒤 관련 3개 재실행 통과. 기존 테스트 전체를 반복하지 않았다.
- Spring 실제 PostgreSQL 테스트 20개 통과, 프런트 단위 테스트 14개·lint·TypeScript·production build 통과.
- 브라우저 회귀 21개 통과. 편집 입력 필드의 명시적 접근성 이름 추가 및 태그 테스트 선택자 수정 후 해당 실패를 해결했다. 최종 기본 회귀는 20개 통과/태그 1개 실패였고, 태그 단독 재실행은 1.7초에 통과했다.
- FastAPI/Spring 계약, 100개 동시 요청의 멱등성과 버전 충돌, 2개 API 간 이벤트 전달, 세션 만료·멤버 제거·프로젝트 삭제 시 접근 종료 확인.
- 별도 빈 테스트 DB에서 upgrade → downgrade → upgrade → Alembic check 통과, 최종 head `b822001`.
- 장애 진단은 최대 240초로 제한했고 실제 **22.2초**에 끝났다. 생성 재전송의 ID가 같고 노드는 정확히 2개, pageerror는 0개였다.
- 브라우저 강제 GC 후 탭별 heap은 약 5.5–5.8MB → 새로고침 후 5.8MB. 재시작 후 API 메모리는 각각 약 70.6MiB였다. 짧은 진단값이며 장기 누수나 고부하 운영 안정성의 증거는 아니다.

편집창 복원과 멤버 관리 스크린샷도 직접 확인했다. 실행 로그는 Git에서 제외한 `deploy/validation-logs/phase3-*.log`, 브라우저 캡처는 `frontend/test-results*/`에 있다.

## 성능

[전체 표본과 환경](measurements/phase3-2026-09-22.json). Windows/i5-13600KF/Chromium 153 production build에서 2단계와 같은 fixture·검색어를 사용했다. 검색 14회 중 초기 2회를 제외한 p95이며, 초기 로딩은 단일 측정이다.

| 노드 | 검색 p95: 2단계 → 이번 | 초기 로딩: 2단계 → 이번 |
| --- | ---: | ---: |
| 1,000 | 73.7 → 34.3ms | 735.5 → 747.8ms |
| 5,000 | 803.5 → 63.7ms | 1,958.3 → 1,710.8ms |

검색은 다수 일치/일치 없음의 교대 조건이다. 모든 임의의 검색·레이아웃에서 같은 성능을 보장하지 않는다. 초기 요청은 노드 1회·태그 1회다. 기존 1천 노드 회귀 기준 300/200ms도 검색 34.6ms·접기 38.0ms로 통과했다.

동일 새 API에서 전체 조회와 변경 없는 조건부 조회를 교대 42회 실행하고 초기 2회를 제외했다. API당 2 CPU·1GiB, 전용 `brainnet_test` DB를 사용했다.

| 노드 | 전체 조회 p95 | 변경 없는 조회 p95 | 본문 bytes: 전체 → 변경 없음 |
| --- | ---: | ---: | ---: |
| 1,000 | 65.44ms | 8.73ms | 256,733 → 0 |
| 5,000 | 152.90ms | 22.33ms | 1,307,777 → 0 |

ETag 계산은 DB에서 노드·태그·연결을 읽어 fingerprint를 만든다. 변경된 그래프는 전체 스냅샷을 받으며, 서버 증분 전송이나 페이지네이션을 구현한 것은 아니다. 304에서도 멤버 권한을 검사한다.

## 배포와 재현

로컬 Docker `brainnet-local`에 배포했다. UI `http://localhost:3000`, API `http://localhost:18000`. 세 컨테이너 healthy, 로그인 HTTP 200, 이벤트 ready=true, DB head `b822001` 확인. `.tools/local-before-phase3.sql`에 먼저 백업했고 프로젝트 1개·노드 2개 및 노드/멤버 전체 행 fingerprint가 배포 전후 동일했다. AI 키는 없는 기본 수동 모드다.

```powershell
# 기본 회귀: 개인 DB와 분리된 검증 스택
./deploy/validate-next.ps1 -KeepRunning

# 추가 진단: 위 스택이 실행 중일 때
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD/.tools/playwright"
$env:JWT_TOKEN = docker compose -p brainnet-next-validation -f deploy/local-validation.compose.yml exec -T tools python -c 'from app.core.security import create_access_token; print(create_access_token("7"))'
$env:PHASE3_STABILITY = '1'
cd frontend
node node_modules/@playwright/test/cli.js test e2e/stability.spec.ts --output=test-results-stability
$env:PHASE2_PERF = 'phase3'
node node_modules/@playwright/test/cli.js test e2e/performance.spec.ts --output=test-results-performance
```

JWT는 기본 검증 seed의 사용자 7을 위한 테스트 토큰이다. API 조건부 조회 측정은 tools 컨테이너에서 `MEASURE_CONDITIONAL_READS=1`로 `backend/scripts/measure_graph_reads.py`를 실행한다. 이 스크립트는 명시적으로 허용한 전용 테스트 DB에서만 동작한다.

초안은 같은 탭에서 닫기·새로고침 후 복원한다. 닫힌 탭 전체의 초안 탐색, 오프라인 자동 전송, 충돌 자동 병합, 장시간 부하 검증, 유료 AI 호출 성공·비용 검증은 이번 완료 범위에 포함하지 않는다. 원격 CI 상태는 [현재 브랜치 Actions](https://github.com/PHJ2000/BrainNet_V2/actions?query=branch%3Afeat%2Fnext-local-workflow)에서 별도로 확인한다.

### 원격 회귀에서 발견한 가지 접기 지연

첫 원격 CI의 다른 4개 job과 브라우저 기능 20개는 통과했으나, Linux runner의 접기 p95 292.1ms가 기존 200ms 기준을 넘었다. Cytoscape 설치 소스에서 `display:none`이 연결선과 평행선의 bounds를 다시 계산하는 것을 확인했다. 고정 좌표를 유지하는 `visibility:hidden`으로 변경하고 연결선도 명시적으로 숨긴다. 숨겨진 노드가 입력을 받지 않는 회귀를 추가했다. 로컬 탐색·접기 2개와 1천/5천 노드 측정 2개만 다시 실행했고 각각 4.8초/4.2초에 통과했다. 기준은 완화하지 않았다. 표와 측정 JSON의 `browser_phase3`는 최종 수정 후 값이며 최초 값도 보존했다.
