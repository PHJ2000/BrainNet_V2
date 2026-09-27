# 노드 이력·활동·지표·멤버 관리

이 문서는 Spring 백엔드 API를 설명한다. 로컬 앱 API 주소는 `http://localhost:18000`이며,
보호된 요청에 `Authorization: Bearer <access_token>`을 전달한다. 해당 기능의 프론트 화면은 별도 작업이다.

## 노드 내용 이력과 복원

| 요청 | 동작 |
| --- | --- |
| `GET /projects/{p}/nodes/{n}/versions` | 저장된 버전을 최신순으로 조회 |
| `GET /projects/{p}/nodes/{n}/versions/{v}` | 특정 버전 내용 조회 |
| `POST /projects/{p}/nodes/{n}/versions/{v}/restore` | 해당 내용을 새로운 버전으로 복원 |

목록은 `limit`(기본 50, 최대 100), `before_version`으로 페이지를 나눈다.
응답 필드는 `id`, `node_id`, `version_no`, `content`, `author_id`, `created_at`이다.

생성한 노드는 버전 0부터 내용을 기록한다. 수정·좌표 변경·활성화·비활성화로 버전 번호가
증가할 때에도 내용 스냅샷을 저장한다. 이력의 `author_id`는 해당 변경을 수행한 사용자다.
기존 노드는 마이그레이션 당시의 현재 내용과 버전을 초기 스냅샷으로 보존한다.
이전 수정자는 알 수 없으므로 이 스냅샷의 `author_id`는 null이며 과거 내용을 만들어내지 않는다.

예를 들어 현재 버전이 5인 노드의 내용을 버전 2로 복원한다.

```http
POST /projects/1/nodes/10/versions/2/restore
Content-Type: application/json
Authorization: Bearer <access_token>

{"expected_version":5}
```

성공하면 버전 6에 버전 2의 내용을 저장한다. 좌표·상태·부모 관계·태그는 현재 값을 유지한다.
`expected_version` 누락은 428, 다른 수정으로 버전이 바뀌었으면 409다.
복원과 일반 수정을 동시에 보내도 같은 현재 버전에서 한 요청만 성공한다.
응답 유실 후에는 현재 노드를 다시 조회해 결과를 확인한다.

이 기능은 **노드 내용 복원**이며 마인드맵 전체나 삭제된 노드를 되살리는 기능은 아니다.
노드 삭제 시 해당 노드의 내용 스냅샷도 삭제된다. 삭제 행위 자체는 활동 기록에 남는다.
내용 변경, 스냅샷, 활동 기록, WebSocket 알림용 outbox는 같은 트랜잭션에 저장한다.

## 활동 기록

`GET /projects/{p}/activities`는 프로젝트 멤버가 활동을 최신순으로 조회하는 API다.
`limit`은 기본 50, 최대 100이며, 다음 페이지는 마지막 항목의 `id`를 `before_id`로 전달한다.
`type=NODE_RESTORE`처럼 유형별로 필터링할 수 있다. 알 수 없는 유형과 잘못된 페이지 값은 422다.

기록하는 행위:

- 프로젝트 생성·수정·삭제.
- 노드 생성·수정·삭제·복원·활성화·비활성화.
- 태그 생성·수정·삭제·부착·제거, 태그 요약 생성.
- 투표·확정, 초대 발송·참여.
- 멤버 강퇴·탈퇴·소유권 이전.

응답은 `id`, `user_id`, `project_id`, `type`, `payload`, `logged_at`이다.
payload에는 대상 ID·버전·처리 개수 같은 메타데이터를 저장한다. 로그인 토큰, 초대 토큰,
비밀번호와 노드 본문은 기록하지 않는다. 변경이 롤백되면 활동 기록도 함께 롤백된다.
이미 처리된 생성 요청의 재시도, 같은 요약 재생성, 같은 역할 설정은 중복 기록을 만들지 않는다.
삭제된 프로젝트의 활동 기록은 DB에 보존하지만 일반 프로젝트 API로는 조회할 수 없다.

## 노드 지표

| 요청 | 동작 |
| --- | --- |
| `GET /projects/{p}/nodes/{n}/metrics` | 해당 노드 하위 트리 지표 계산·저장·조회 |
| `GET /projects/{p}/metrics` | 프로젝트 모든 노드의 지표 계산·저장·조회 |

- `subtree_size`: 자신을 포함한 전체 하위 노드 수. GHOST·ARCHIVED도 센다.
- `density_score`: 하위 트리의 ACTIVE 노드 수 / `subtree_size`. 0~1 범위의 활성 비율이다.
- `updated_at`: 지표를 계산한 시각.

예를 들어 자신을 포함해 4개 노드 중 3개가 ACTIVE면 크기는 4, 밀도는 0.75다.
좌표상의 배치 밀도나 그래프의 간선 밀도를 나타내는 값은 아니다.
노드 변경 시 저장된 지표를 무효화하고 조회 시 현재 DB로 다시 계산한다.
계산 중에는 프로젝트 변경을 잠시 잠가 생성·삭제와 계산 결과가 섞이지 않도록 한다.
이전 데이터에 잘못된 부모 순환이 있어도 재귀 조회가 무한 반복되지 않는다.

## 멤버와 소유권 관리

| 요청 | 권한·동작 |
| --- | --- |
| `GET /projects/{p}/members` | 멤버 목록 조회. 모든 멤버 가능 |
| `PATCH /projects/{p}/members/{user_id}` | 소유자가 역할 변경 |
| `DELETE /projects/{p}/members/{user_id}` | 소유자가 다른 멤버 강퇴 |
| `DELETE /projects/{p}/members/me` | 자신의 프로젝트 탈퇴 |

목록은 `user_id`순이다. `limit`(기본·최대 100), `after_user_id`로 다음 페이지를 조회한다.
목록에는 사용자 ID·이름·이메일·역할·초대/참여 시각을 반환한다.
기존 역할인 OWNER와 EDITOR를 사용하며 VIEWER 역할은 제공하지 않는다.

```http
PATCH /projects/1/members/22
Content-Type: application/json
Authorization: Bearer <현재 소유자의 access_token>

{"role":"OWNER"}
```

위 요청은 기존 멤버 22에게 소유권을 이전한다. 기존 소유자는 EDITOR가 되며
`project.owner_id`와 두 멤버의 역할이 함께 갱신된다. 동시에 소유권 이전을 요청해도 소유자는 한 명이다.
현재 OWNER를 바로 EDITOR로 내리거나 강퇴·탈퇴시키면 `409 OWNERSHIP_TRANSFER_REQUIRED`다.
먼저 다른 멤버에게 소유권을 넘긴 뒤 탈퇴할 수 있다.

강퇴·탈퇴 시 해당 멤버십과 해당 계정의 프로젝트 초대 정보, 진행 중인 투표를 제거한다.
작성했던 노드, 과거 버전, 활동 및 확정 기록은 보존한다. 다시 참여하려면 새 초대가 필요하다.
새 REST 요청은 403으로 차단되고, 멤버십 변경과 이미 진행 중인 쓰기는 프로젝트 잠금으로 처리 순서를 정한다.
삭제된 프로젝트는 목록에서 제외하고 관련 API가 404를 반환한다.

FastAPI WebSocket은 매 이벤트 전 현재 멤버십을 확인한다. 강퇴·탈퇴·프로젝트 삭제 시
기존 연결을 4403으로 닫으며, 이벤트가 없는 동안에도 15초마다 확인한다.
JWT 만료는 4401, 권한 확인 DB 장애는 1013으로 닫는다.
새 `membership.changed`, `project.deleted` outbox 이벤트는 모든 worker에 전달된다.

## 적용·롤백 범위

Compose를 다시 빌드·시작하면 Alembic `c2f4a6b8d010`을 적용한 뒤 Spring을 시작한다.
이 마이그레이션은 활동 유형·조회 인덱스를 추가하고 기존 노드의 현재 내용 스냅샷을 저장한다.
확장된 유형의 활동 기록이 있으면 데이터 손실 방지를 위해 스키마 downgrade를 거절한다.
일반 앱 롤백은 DB를 유지한 채 라우팅으로 진행한다.

새 API와 이력·활동 기록 쓰기, 지표 무효화는 Spring 전용이다. 기존 Python REST로 롤백하는
동안의 변경에는 이 기록이 추가되지 않는다. WebSocket 권한 재확인은 Python에서 계속 적용된다.
REST 구현을 혼합해 동시에 쓰는 운영 방식은 이 기능의 지원 범위가 아니다.

## 로컬 검증

- Spring 기존 39개와 관리 기능 11개 검증: 내용 복원 충돌, 과거 이력 보존, 지표 무효화,
  활동 저장 실패 시 전체 롤백, 소유권 이전 경쟁, 강퇴·탈퇴 권한과 프로젝트 격리.
- Python 65개 검증: 실제 PostgreSQL에서 멤버십 제거·프로젝트 삭제 후 WebSocket 전송 차단,
  만료·DB 장애·유휴 연결의 권한 재확인, 기존 노드·이벤트 회귀 검사.
- 별도 DB에 기존 노드를 만든 뒤 마이그레이션하여 현재 버전 보존과 중복 방지를 확인했다.
  손실을 유발하는 활동 enum downgrade는 거절하며, 허용되는 downgrade/upgrade와 빈 DB 재생성은 통과했다.
- 전체 downgrade 시 예전 enum 타입이 남아 재생성을 막던 초기 마이그레이션도 수정했다.
