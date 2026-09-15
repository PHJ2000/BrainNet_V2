# BrainNet 다음 버전 로컬 검증 — 2026-09-13

대상은 #7의 출시 필수 이슈 #8 → #9 → #10 → #11이다. 기준 코드는 `main e60bad4105eafcf7da566238b8d9038f1bf6f5db`, 구현은 로컬 `feat/next-local-workflow` 작업 트리다. #12~#14는 후속 백로그다. 외부 운영 서버를 구매하지 않으며 기본 로컬 프로필의 AI 키는 비어 있다.

## 구현 결과

| 이슈 | 동작 | 계약 문서 |
|---|---|---|
| #8 | 일반 생성·본문/위치 수정·가지 삭제의 기록, 미리보기, 자기 작업 실행 취소. 삭제된 관계도 복구하며 버전 충돌 시 전체 거부 | [기록/복구](node-operation-history.md) |
| #9 | 본문 검색, OR 태그 필터, 가지 접기와 숨긴 결과 이동. 계정/프로젝트별 접기 보존, 태그 이벤트 반영 | [탐색 규칙과 측정](graph-explorer.md) |
| #10 | 전체/선택 가지 Markdown 다운로드. 표시 필터와 독립된 원본 범위, 상태 옵션, 원문 보존 | [파일 안내](../backup/README.md) |
| #11 | JSON v1 다운로드, 검증/미리보기, 새 프로젝트 복원. 응답 유실과 새로고침 후 같은 요청 재사용 | [Schema/예제/한도](../backup/README.md) |

자동 생성된 루트/AI 결과·태그 편집 자체는 undo 범위가 아니다. 30일 이전 복구 자료는 만료된다. JSON은 프로젝트 자료를 옮기는 파일이며 계정/권한/투표/메트릭/변경 기록을 포함한 DB 전체 백업은 아니다.

## 실행 검증

- 전용 PostgreSQL 15에서 백엔드 **96 passed**, 기존 deprecation 경고 103개. 런타임 Outbox worker를 중지한 상태에서 실행했다. 테스트 DB와 개인 DB를 공유하지 않는다.
- 프런트 단위 테스트 **12 passed**, production 빌드 및 ESLint 통과. 검증 보조 스크립트의 CommonJS import lint 오류를 ES module로 수정하고 재검사했다.
- Chromium **5 passed (27.8초)**: 수정 응답 유실과 충돌, 두 화면의 변경 기록/삭제 복구, 검색/태그/접기, 실제 Markdown/JSON 파일 저장, 복원 응답 3회 유실 후 새로고침과 같은 요청 복구.
- 복원한 프로젝트는 DB/API 컨테이너 재생성 뒤 새 로그인으로 열어 확인했다. 작업 기록 14건, 복구 payload 12건, 가져오기 영수증 2건의 재생성 전후 fingerprint도 동일했다. 재시작 검증은 in-memory 세션 재사용에 의존하지 않는다.
- 기존 FastAPI/Spring 계약 probe 통과: 양방향 재요청, 혼합 런타임 100개 동시 생성 요청, 100개 동시 PATCH. 이벤트 probe도 두 인스턴스 fan-out, 중복 억제, listener 복구/재접속을 통과했다.
- Alembic head `b811001`, metadata 비교에서 추가 migration 없음. 새 테이블은 `node_operation`, `project_import`다.
- 별도 빈 DB에 처음부터 head를 적용한 뒤 `4c389bbebfad`까지 downgrade → head 재적용 → metadata check를 통과했다. 이 임시 DB만 제거했다.

## 기존 로컬 적용

`brainnet-local` 3개 서비스의 새 이미지를 빌드하고 시작했다. 개인 DB의 `9e1c2a7d4b10` → `b811001` migration이 완료됐다. 기존 계정 1개/프로젝트 1개/노드 2개를 유지했고 프로젝트/노드 전체 행 fingerprint가 전후 동일하다. 기존 프로젝트의 인증된 API 조회와 JSON export도 노드 2개를 반환했으며 과거 변경 기록을 만들어 넣지 않았다. API health/events와 로그인 페이지 응답도 정상이다.

적용 전 DB dump는 개인 임시 폴더의 `brainnet-local-before-next-20260913.dump`에 따로 보관했고 저장소 결과물에는 포함하지 않았다. `.env.local`과 `brainnet-local_local-db` 볼륨은 유지했다. 기본 설정의 paid AI 키는 비어 있음을 확인했다.

원격 커밋/푸시/PR과 GitHub Actions 실행은 이번 로컬 적용 결과에 포함하지 않는다. 원격 CI가 통과했다고 주장하지 않으며 총괄 이슈의 출시 체크는 별도로 남긴다.

검증 종료 뒤 `brainnet-next-validation` 컨테이너/네트워크를 정리했다. 현재 실행 중인 것은 개인 로컬 앱의 DB/backend/frontend 3개이며 모두 healthy다. #7~#11에는 확인한 결과와 남은 출시 확인을 반영했다.

증거는 [이번 실행 폴더](../../experiments/runtime-nodes/results/next-version-2026-09-13/)에 보관한다. 다운로드 검증 자료는 합성 프로젝트이며 테스트 계정 비밀번호/JWT는 포함하지 않는다. 실제 로컬 Markdown 편집기의 수동 검토를 자동 파일 대조와 같은 검증으로 주장하지 않는다.

## 백업 상한 실측

노드 5,000개, 태그 5,000개, 연결 50,000개, 깊이 100의 파일을 실제 DB에 복원하고 다시 내보냈다. 입력은 UTF-8 3,091,721 bytes, 파싱/검증 1,924.5 ms, Python 추적 메모리 최고 53.4 MiB, DB 복원 12,216.3 ms였다. 노드/태그/관계 건수가 모두 일치했다. 메모리는 파싱 중 Python allocation의 추적값으로 전체 컨테이너 RSS가 아니다.

10 MiB는 파싱 전의 하드 제한이다. 이 실측 파일이 10 MiB였다는 뜻은 아니다. 초과 크기, 손상 JSON, 참조/상태/깊이 오류, 불완전한 Unicode를 거부하는 별도 테스트가 있다. 5,000개 백업 지원과 화면 반응성 검증 범위(1,000개)는 구분한다. [원시 측정](../../experiments/runtime-nodes/results/next-version-2026-09-13/backup-limits.json)

## 부하 한계

동일 PC/Docker 환경에서 일반 노드 생성 경로를 비교했다. 런타임 자원 제한은 각각 2 CPU / 1 GiB이고 유료 provider 호출은 없다.

| 실행 | 성공/전체 | 실패율 | 성공 RPS | 성공 응답 p95 |
|---|---:|---:|---:|---:|
| 새 버전, 동시 30, 10초 | 421/421 | 0% | 40.503 | 1,202.186 ms |
| 새 버전, 동시 300, 20초 | 1,034/1,247 | 17.081% | 42.932 | 7,094.993 ms |
| 기존 main 이미지, 동시 300, 20초 | 1,046/1,210 | 13.5537% | 43.420 | 7,173.450 ms |

**동시 300 조건은 신·구 버전 모두 실패했다.** 새 버전에서는 503 213건, 기존 버전에서는 503 123건/클라이언트 timeout 41건이었다. 새 버전이 고부하 목표를 통과했다고 표시하지 않는다. 이 1회 비교만으로 원인을 이력 저장이나 Docker 환경 하나로 단정할 수도 없다.

새 버전 동시 30에서는 실패/중복 없이 DB 결과가 일치했고 Outbox 잔량은 0이다. 기존 버전 timeout 뒤 커밋된 31건도 별도로 대조했다. 2026-09-12의 과거 1시간 soak와 성능 개선율은 이번 버전에서 새로 재현한 결과가 아니다. 이번 로컬 사용 확인을 다중 사용자 운영 용량 보증으로 확대하지 않는다.

## 반복 실행

PowerShell과 Docker, Node.js가 필요하다. 저장소 루트에서 실행한다.

```powershell
./deploy/validate-next.ps1
./deploy/start-local.ps1
```

검증 스크립트는 고정된 `brainnet-next-validation` 스택만 사용한다. DB migration/실제 DB 테스트 → 프런트 검사 → production 서버 → FastAPI/Spring 계약과 두 인스턴스 이벤트 → Chromium → DB/API 컨테이너 재생성 및 로그인 순서다. 실패 시 비정상 종료와 임시 폴더 로그를 남기며 기본 실행은 종료 시 검증 컨테이너를 정리하고 테스트 볼륨만 보존한다. 개인 `brainnet-local_local-db`에는 reset/seed를 실행하지 않는다.

`-MeasureLimits`는 최대 백업 fixture를 추가한다. `-SkipBuild`는 이미 최신 runtime 이미지를 빌드한 경우에만 쓴다. `-RuntimeOnly`는 이미 통과한 DB 테스트 뒤 브라우저/런타임 검증만 재개하며 전체 테스트 통과로 간주하지 않는다. `-KeepRunning`은 명시적으로 검증 컨테이너를 남기는 디버깅 옵션이다.

사용 앱은 http://localhost:3000, API는 http://localhost:18000 이다. 기존 `.env.local`과 DB 볼륨을 유지하며 마이그레이션이 적용된다. 별도 paid API나 운영 서버 설정은 필요하지 않다.
