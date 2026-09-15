# PHJ2000 기여 내역

> 기준일: 2026-09-06 (KST)
> 대상 저장소: [PHJ2000/BrainNet_V2](https://github.com/PHJ2000/BrainNet_V2)
> 기본 브랜치: `main`

## 요약

PHJ2000은 저장소 소유자이자 핵심 구현자로서 초기 FastAPI 백엔드 구성과 데이터 모델·라우터를 만들고, 이후 Java 25/Spring 전환 방향을 ADR로 정리했다. Spring vertical slice와 점진적 cutover 계약을 구현하며 기존 Python 서비스에서 Spring 서비스로 책임을 이동하는 작업을 진행했다.

| 구분 | 확인 결과 |
| --- | ---: |
| `main` 반영 커밋 | 37개 (일반 29개, merge 8개) |
| 전체 원격 ref의 작성 커밋 | 38개 (일반 30개, merge 8개) |
| 작성 PR | 5개 (merged 4, open 1) |
| 작성 이슈 | 0개 |
| 다른 기여자의 PR에 제출한 리뷰 | 0회 |
| 자기 PR의 점검성 리뷰 | 4회 |
| 리뷰 라인 코멘트 | 2개 |
| 이슈·PR 대화 코멘트 | 1개 |

리뷰·댓글 수는 서로 겹칠 수 있으므로 합산해 하나의 총 기여 수로 사용하지 않는다.

## 커밋 기여

- 활동 기간: 전체 원격 ref 기준 2025-05-15 ~ 2026-08-29
- `main` 반영 기간: 2025-05-15 ~ 2026-08-24
- 주요 변경 지점: README, FastAPI node/project/tag/user/vote/history 모델과 라우터, DB session 및 모델, Spring vertical slice, 통합 테스트, CI workflow
- 비-merge 커밋 제목 기준 주요 유형: `feat` 9개, `fix` 7개, `docs` 6개, `test` 1개와 초기 비정형 제목 커밋

## PR 기여

현재 GitHub PR 5개는 모두 PHJ2000이 작성했다.

- [#1 Java 25 + Spring 전환 ADR 및 실험 근거](https://github.com/PHJ2000/BrainNet_V2/pull/1) — merged
- [#2 ADR 기반 마이그레이션 계약](https://github.com/PHJ2000/BrainNet_V2/pull/2) — merged
- [#3 Spring project/node vertical slice](https://github.com/PHJ2000/BrainNet_V2/pull/3) — merged
- [#4 node 생성 책임을 Spring으로 이전](https://github.com/PHJ2000/BrainNet_V2/pull/4) — merged
- [#5 단계적 Spring 운영 전환 계획](https://github.com/PHJ2000/BrainNet_V2/pull/5) — open

[PHJ2000 작성 PR 전체 보기](https://github.com/PHJ2000/BrainNet_V2/pulls?q=is%3Apr+author%3APHJ2000)

## 코드 리뷰 기여

다른 기여자가 작성한 PR에 대한 공식 리뷰는 확인되지 않았다. PHJ2000이 작성한 PR 4개에는 총 4회의 `COMMENTED` 리뷰가 있으며, 이는 동료 승인과 구분되는 작성자 자체 점검·설명 기록이다. 별도로 리뷰 라인 코멘트 2개와 PR 대화 코멘트 1개가 확인된다.

## 이슈 및 기타 기여

GitHub Issues에 PHJ2000이 작성한 이슈는 기준일 현재 없다. 작업 추적과 설계 결정은 PR, README, ADR 및 migration 문서를 중심으로 관리됐다.

기타 핵심 기여는 다음과 같다.

- 초기 FastAPI 애플리케이션, DB 모델과 주요 도메인 라우터 구성
- CI workflow 유지보수
- Java 25/Spring 전환 타당성 검증과 ADR 작성
- Python/Spring 간 마이그레이션 계약 및 vertical slice 통합 테스트 구축
- node 생성 책임의 단계적 이전과 운영 cutover 계획 문서화

## 집계 기준

- 커밋은 `git fetch --all --prune` 후 작성자 이름/이메일을 기준으로 중복 SHA 없이 집계했다.
- 포함한 작성자 표기: `박재홍`, `Park Jae Hong`의 GitHub noreply 주소와 `Park Jae  Hong <koreaworldclass@gmail.com>`.
- GitHub 활동은 로그인 `PHJ2000`을 기준으로 GitHub API에서 조회했다.
- 기본 브랜치 수치는 반영 완료 기여를, 전체 원격 ref 수치는 open/미반영 브랜치까지 포함한 작성 활동을 뜻한다.
- PR/리뷰 상태는 기준일 이후 변경될 수 있다.
