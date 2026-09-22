# BrainNet V2 — 2단계 결과

2026-09-22. 기준 커밋은 1단계 `8e519fe34c23a5e6d9c4fcbd0c2455e5e0003aef`, 작업 브랜치는 `feat/next-local-workflow`다. [7일 계획](WEEKLY_IMPROVEMENT_PLAN_2026-09-22.md)의 4~7일차 범위를 구현했다. 실제로 일주일이 경과했다는 의미는 아니다.

## 변경 사항

- 대시보드에 프로젝트 이름 검색, 이름순·최근 생성순 정렬을 연결했다. 한글 NFC 정규화를 적용하고 전체 빈 목록, 검색 결과 없음, 조회 실패를 구분한다.
- 프로젝트·노드 조회 실패에 재시도를 제공한다. 서버 오류를 삭제된 프로젝트로 표시하지 않으며, 화면 이동 시 이전 요청을 취소한다.
- 그래프에 연결·재연결 상태와 노드 편집·생성·위치 저장 상태를 표시한다. 실패한 입력과 작업을 유지하고 수동 재시도 시 같은 멱등키를 사용한다. 409 버전 충돌에서는 쓰기를 재시도하지 않고 최신 상태 확인과 입력 버리기를 제공한다.
- 편집 이벤트와 저장 상태를 `useGraphEditing`·`useSaveOperation`으로 분리하고, 10개 FastAPI 라우터의 DB 세션 의존성을 공통화했다. 태그 트랜잭션 전체 재작성은 하지 않았다.
- 겹친 초기 WebSocket 재동기화·조회 요청을 합쳤다. 쓰기 완료 뒤에는 진행 중이던 읽기보다 새로운 조회를 보장한다. 동일 노드 객체와 텍스트 측정 canvas를 재사용하고, 그래프 전체 삭제·재생성 대신 변경분을 반영한다. 검색 시 스타일 변경은 묶어서 적용한다.
- README의 Outbox 전달 미구현 설명을 현재 PostgreSQL NOTIFY/LISTEN → WebSocket 흐름에 맞췄다.

## 실제 검증

개인 데이터 대신 `brainnet-next-validation` / `brainnet_test`를 사용했다.

| 검증 | 결과 |
| --- | --- |
| 백엔드 전체 + PostgreSQL 회귀 | 145개 통과 (`phase2-validation.log`) |
| 프론트 단위 테스트 / lint / production build | 14개 통과, lint·빌드 성공 |
| 최종 Chromium 기능 회귀 | 15개 통과, 별도 실행용 성능 테스트 2개 skip |
| 고정 1천·5천 노드 성능 테스트 | 별도 실행 2개 통과, 수치는 아래 표 |
| FastAPI·Spring 차등 계약 / 이벤트 전달 | 100 writer, 양방향 멱등 응답, 두 인스턴스 전달·복구 통과 |
| 실제 WebSocket 세션 검사 | 만료·멤버 권한 제거·프로젝트 삭제에 따른 연결 종료 통과 |
| DB 재생성 / 백업 복구 | 이력·복원 receipt fingerprint 유지, 새 로그인과 복원 노드 재조회 통과 |
| 새 사용성 시나리오 | 조회 실패 복구, 검색·정렬, 저장·생성 재시도 키 유지, 충돌 시 읽기만 수행, 재연결, 프로젝트 이동 후 이전 입력 격리 |

최종 통합 기록: `deploy/validation-logs/phase2-final-runtime.log`와 `brainnet-next-validation-20260922-150159.log`. 저장 실패 화면의 입력·버튼 배치는 `frontend/test-results/.../save-retry.png`를 열어 확인했다. 새 실패 시나리오는 브라우저 API/WS 모킹이며, 실제 서버의 멱등성과 이벤트 전달은 별도 PostgreSQL·네트워크 검증으로 확인한다.

Spring 소스와 의존성은 이번 단계에서 바꾸지 않았다. 1단계에서 실행한 Spring Testcontainers 19개와 빈 DB 마이그레이션 왕복·패키지 감사 결과는 [1단계 보고서](PHASE1_RESULT_2026-09-22.md)에 있으며, 이번 단계의 신규 실행 수치로 합산하지 않는다.

## 같은 조건의 전후 측정

브라우저: Windows, i5-13600KF, RAM 64 GiB, Chromium 153.0.8010.12, production build, 고정 좌표·깊이 20의 모킹 데이터. 검색을 14회 교대로 실행하고 첫 2회를 제외한 12회의 nearest-rank p50/p95다. 초기 로딩은 1회 측정값이며 별도의 p95가 아니다. [원본 측정값](measurements/phase2-2026-09-22.json)에 모든 표본을 남겼다.

| 노드 | 초기 로딩 전 → 후 | 검색 p50 전 → 후 | 검색 p95 전 → 후 | 초기 노드 GET / 태그 GET |
| --- | ---: | ---: | ---: | --- |
| 1,000 | 680.2 → 735.5ms | 56.8 → 37.3ms | 111.2 → 73.7ms | 2 / 2 → 1 / 1 |
| 5,000 | 2,308.9 → 1,958.3ms | 540.8 → 407.2ms | 860.5 → 803.5ms | 2 / 2 → 1 / 1 |

브라우저 fixture의 JSON 응답은 각각 164,689 / 844,260 bytes로 전후 동일하다. 첫 최적화에서 5천 노드 p95가 1,017.3ms로 악화되어 그대로 채택하지 않았다. Cytoscape scratch setter가 스타일 계산을 다시 실행하는 것을 설치된 소스에서 확인하고, 외부 Map 캐시와 묶음 스타일 적용으로 수정한 뒤 위 결과를 얻었다.

API: 동일 PostgreSQL 테스트 DB, 앱별 2 CPU·1 GiB, 두 런타임 모두 이벤트 전달 활성화. 동일 fixture를 양쪽에 읽으며 순서를 번갈아 실행했다. 런타임당 42회에서 첫 2회를 제외한 40회의 p50/p95다.

| 노드 | API p50 전 → 후 | API p95 전 → 후 | 응답 bytes 전후 동일 |
| --- | ---: | ---: | ---: |
| 1,000 | 18.81 → 18.95ms | 56.24 → 58.54ms | 261,777 |
| 5,000 | 118.10 → 116.44ms | 142.64 → 143.47ms | 1,319,809 |

API 성능 개선을 주장하지 않는다. p95 차이는 각각 약 +4.1%, +0.6%로 이번 계획의 10% 악화 기준 이내다. 최초 순차 10표본 측정의 단발성 이상치는 동일 설정·교대 순서·40표본 비교로 재검증했다. 최종 기존 1천 노드 회귀에서는 검색 p95 70.5ms, 접기 p95 59.1ms로 기존 300/200ms 기준을 통과했으며 기준을 완화하지 않았다. 5천 노드 검색은 여전히 약 0.8초이며, 이 측정은 대규모 동시 사용자 부하 검증이 아니다.

## 실행과 배포

```powershell
# 전용 DB에서 전체 검증
./deploy/validate-next.ps1 -KeepRunning

# 실행 중인 production 검증 UI의 고정 fixture 측정
cd frontend
$env:PHASE2_PERF = 'after'
npx playwright test e2e/performance.spec.ts
```

API 비교는 `backend/scripts/measure_graph_reads.py`를 사용한다. `BASELINE_API_URL`과 `FASTAPI_BASE_URL`이 같은 테스트 DB를 바라보도록 준비해야 하며, `brainnet_test`와 `ALLOW_TEST_DATABASE_RESET=1` 조건에서만 실행된다. 생성한 측정 fixture는 finally에서 정리한다.

1단계는 `8e519fe`를 원격 브랜치에 푸시하고 로컬 Docker에 배포했다. 2단계도 같은 `brainnet-local` 프로필에 배포했다. UI는 `http://localhost:3000`, API는 `http://localhost:18000`이다. 로그인 페이지 HTTP 200, 이벤트 health의 ready=true, 세 컨테이너 healthy를 확인했다. 개인 DB는 배포 전 `.tools/local-before-phase2.sql`로 백업했으며 프로젝트 1개·노드 2개 및 노드 전체 행 fingerprint가 배포 전후 동일했다. 백업과 비밀 설정은 Git에 포함하지 않는다.

원격 실행 결과는 [브랜치의 GitHub Actions](https://github.com/PHJ2000/BrainNet_V2/actions?query=branch%3Afeat%2Fnext-local-workflow)에서 확인한다. 1단계 원격 실행에서 브라우저 성능 기준 실패가 발견되어 이번 스타일 갱신 최적화로 함께 수정했다. 로컬 통과와 원격 CI 통과는 별개로 확인한다.

## 남은 범위

- 저장 상태·재시도는 노드 편집·생성·위치 변경 대상이다. 태그·투표의 트랜잭션과 전체 오류 UX 재설계는 후속 범위다.
- 입력 보존은 현재 페이지 메모리 안에서 제공한다. 새로고침 후 오프라인 큐 복원이나 충돌 자동 병합은 제공하지 않는다.
- 로컬 기본 배포는 AI 키가 없다. 유료 AI 호출의 성공·비용·장시간 동시 부하는 검증하지 않았다.
- 전체 노드 조회와 30초 재동기화는 유지한다. 서버 페이지네이션·증분 조회, 쿠키/WS ticket 인증 전환, 공유 rate limit은 별도 작업이다.
