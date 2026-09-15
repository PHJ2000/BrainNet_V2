# BrainNet 개발 과정과 기여

[프로젝트 README](../README.md#개발팀)

## 초기 팀 프로젝트

팀 역할은 [기존 프로젝트 보고서](./archive/original-project-report.md)의 기록을 따릅니다.

| 이름 | 역할과 담당 |
| --- | --- |
| 김동건 | 팀 리더, 웹 UI, AI 연동 |
| 박재홍 · [PHJ2000](https://github.com/PHJ2000) | 백엔드 아키텍처, FastAPI·PostgreSQL, 데이터 모델·라우터와 API 연동 |
| 이승재 | API 설계, 3티어 환경 구축, Next.js UI·Cytoscape.js 그래프 |

박재홍의 초기 백엔드 작업은 사용자·프로젝트·노드·태그·투표·히스토리 데이터 모델과 DB 연결, 라우터의 실제 DB 연동으로 이어졌습니다.

- [DB 설계와 SQLAlchemy 모델·세션 구성](https://github.com/PHJ2000/BrainNet_V2/commit/a6f392b8a53098a707bf69f093ff4b5a5812e100)
- [주요 API와 데이터 연동 보완](https://github.com/PHJ2000/BrainNet_V2/commit/26c786f2a545be7ed821366877871d573c9684d0)

## 박재홍의 후속 백엔드 개선

2026년 8월에는 기존 앱의 동시성·API 계약을 보완하고, Spring 전환 실험과 일부 API 구현을 진행했습니다.

| 영역 | 구현·검증한 내용 | 근거 |
| --- | --- | --- |
| 비교 실험·설계 결정 | blocking·async FastAPI와 Spring 후보 비교, AI·실시간 통신의 전환 범위 결정 | [PR #1](https://github.com/PHJ2000/BrainNet_V2/pull/1), [ADR 목록](./adr) |
| FastAPI 보완 | 비동기 AI 호출, 인증·오류·요청 추적 계약, 노드 버전·단일 활성 루트 제약 | [PR #2](https://github.com/PHJ2000/BrainNet_V2/pull/2), [노드 라우터](../backend/app/routers/nodes.py) |
| 프론트엔드 상태 정합성 | 수정 버전 전달, 충돌 시 서버 상태 재동기화, 늦은 응답 방어 | [PR #2](https://github.com/PHJ2000/BrainNet_V2/pull/2), [노드 그래프](../frontend/src/features/nodes/Graph.tsx) |
| Spring 조회·수정 | 프로젝트·노드 조회, JWT·멤버십 검증, 버전 기반 조건부 갱신 | [PR #3](https://github.com/PHJ2000/BrainNet_V2/pull/3) |
| Spring 노드 생성 | 일반·AI 생성, 멱등성 응답, 태그 상속·Outbox 원자적 저장, 외부 AI 호출과 DB 트랜잭션 분리 | [PR #4](https://github.com/PHJ2000/BrainNet_V2/pull/4) |
| CI·계약 검증 | PostgreSQL 동시성, Alembic 변경·되돌리기, 이미지 시작, Python·Spring API 계약 비교 | [CI workflow](../.github/workflows/ci.yml), [Spring 통합 테스트](../spring/vertical-slice/src/test/java/com/brainnet/spring/VerticalSliceIntegrationTest.java) |

위 PR #1~#4는 2026년 9월 9일 확인 시 병합 상태입니다. 후속 구현은 초기 3인 팀의 공동 결과와 구분합니다.

## 운영 전환 계획

루트 Compose는 FastAPI를 사용하며 Spring으로 자동 전환하지 않습니다. Spring은 별도 실행하는 프로젝트·노드 API 구현입니다.

[단계적 운영 전환 PR #5](https://github.com/PHJ2000/BrainNet_V2/pull/5)는 2026년 9월 9일 확인 시 미병합 상태입니다. 실제 provider 검증, shadow·canary, 장시간 부하, rollback과 Outbox 이후 이벤트 전달은 구현 병합과 별도로 확인해야 합니다.

[전환 runbook](./migration/adr-rollout-runbook.txt)
