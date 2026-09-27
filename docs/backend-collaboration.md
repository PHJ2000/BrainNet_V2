# 백엔드 초대·요약·투표

Spring REST에서 제공한다. 기존 DB의 `invite_token`, `tag_summary`, `vote`,
`project_history`를 사용하므로 추가 스키마 마이그레이션은 없다.
프론트엔드 초대·참여·투표 UI는 별도 작업이다.

## 로컬 메일

로컬 앱과 개발 Compose는 SMTP를 `mailpit:1025`로 연결한다.
메일은 외부 수신자에게 전송되지 않고 `http://localhost:18025`의 로컬 메일함에 저장된다.
SMTP 포트는 호스트에 공개하지 않는다. 새 구성은 기존 Compose 시작 명령으로 빌드·시작한다.
검증 Compose에도 Mailpit이 있으며 UI 포트는 공개하지 않는다.

직접 실행할 때는 `SMTP_HOST`(기본 localhost), `SMTP_PORT`(1025), `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_AUTH`(false), `SMTP_STARTTLS`(false)를 설정한다.
발신자는 `INVITE_MAIL_FROM`(brainnet@localhost), 유효 기간은 `INVITE_EXPIRY_HOURS`(72, 허용 1~720시간)다.
SMTP 제출 실패는 `503 INVITE_DELIVERY_FAILED`이며 토큰 저장·재발급을 롤백한다.
SMTP 수락과 DB 커밋은 분산 트랜잭션이 아니므로, 수락 직후 DB 커밋 실패나 프로세스 종료가
발생하면 사용할 수 없는 토큰의 메일이 남을 수 있다. 이 경우 소유자가 다시 초대한다.
자동 메일 재시도 큐는 제공하지 않는다.

## 초대·참여 API

모든 요청에는 `Authorization: Bearer <로그인 토큰>`이 필요하다.

1. 소유자: `POST /projects/{project_id}/invite?email=recipient%40example.com`
2. 초대받은 이메일 계정으로 회원가입·로그인한다.
3. 수신자: `POST /projects/join?token=<invite_token>`

초대 응답은 `invite_token`, `project_id`, `email`, `expires_at`, `delivery: "smtp"`다.
토큰은 256비트 난수이며 DB에는 SHA-256 해시만 저장한다. 응답·메일의 원문 토큰으로만 참여할 수 있다.
같은 프로젝트·이메일을 다시 초대하면 이전 토큰은 무효화된다. 이미 멤버인 계정은 초대할 수 없다.
초대는 계정 생성 전에도 가능하다. 이메일 비교는 회원가입과 동일하게 도메인만 소문자로 정규화한다.

참여는 토큰의 프로젝트에 EDITOR 멤버십을 저장하고 `accepted_at`을 함께 갱신한다.
프로젝트·초대 행 잠금으로 동시 수락과 재발급을 직렬화한다.
사용된 토큰은 같은 계정이 재시도해도 409다. 응답 유실 시 프로젝트 목록에서 참여 여부를 확인한다.

| 상황 | 응답 |
| --- | --- |
| 잘못된 이메일·토큰 형식 | 422 |
| 알 수 없거나 재발급으로 무효화된 토큰 | 404 INVITE_NOT_FOUND |
| 초대 이메일과 로그인 계정 불일치 | 403 INVITE_RECIPIENT_MISMATCH |
| 유효 기간 만료 | 410 INVITE_EXPIRED |
| 이미 사용한 토큰 | 409 INVITE_ALREADY_USED |
| 이미 프로젝트 멤버인 수신자에게 초대 | 409 ALREADY_PROJECT_MEMBER |
| 삭제된 프로젝트 | 404 |

기존 Python 초대·참여는 410으로 차단되어 롤백해도 임의 프로젝트에 가입되지 않는다.
프록시와 애플리케이션 요청 로그는 토큰이 들어 있는 쿼리 문자열을 기록하지 않는다.

## 요약 → 투표 → 확정

1. 아이디어를 생성하고 활성화한 뒤 태그를 붙인다.
2. 소유자: `POST /projects/{project_id}/tags/{tag_id}/summary`
3. 멤버: `GET /projects/{project_id}/tags/{tag_id}/summary`로 최신 요약을 확인한다.
4. 멤버: `POST /projects/{project_id}/tags/{tag_id}/vote`
5. 소유자: `POST /projects/{project_id}/votes/confirm`
6. 멤버: `GET /projects/{project_id}/history`로 확정 기록을 조회한다.

요약은 **외부 AI 호출 없는 발췌 방식**이다. 태그의 ACTIVE 노드를 깊이·순서·ID순으로 읽고,
공백을 정리한 뒤 각 노드의 앞 240자를 최대 50개 저장한다. 50개를 넘으면 제한 문구를 붙인다.
빈 내용, `?`, 초기 주제 안내문, GHOST 노드는 제외한다.
활성 아이디어가 없으면 `409 NO_SUMMARIZABLE_NODES`다.
응답은 `id`, `tag_id`, `summary_text`, `created_at`이며, 내용이 같으면 기존 최신 스냅샷을 반환한다.
노드 수정이나 태그 변경이 요약을 자동 갱신하지는 않는다. 투표 전에 소유자가 다시 생성한다.

투표는 해당 태그의 최신 요약에 연결된다. 프로젝트에서 한 표라도 투표되면 모든 태그의
요약 재생성을 `409 VOTING_IN_PROGRESS`로 차단한다. 요약 생성·투표·확정은 같은 프로젝트 행을
잠가 동시에 요청해도 투표 도중 대상 요약이 바뀌지 않는다. 중복 투표는 기존처럼 400이다.
확정은 최다 득표 요약을 선택한다. 소유자는 `winning_tag_id`로 선택할 태그를 지정할 수도 있다.
확정 기록과 이벤트 저장, 진행 중 투표 삭제를 같은 트랜잭션에서 수행한다.

확정 후에는 새 요약을 생성하고 다음 투표를 시작할 수 있다.
`GET /projects/{project_id}/tags/{tag_id}/summaries`는 과거 스냅샷까지 최신순으로 반환한다.
히스토리의 `tag_summary_id`로 확정 당시 내용을 찾을 수 있다.
투표 또는 확정 기록이 참조하는 태그 삭제는 `409 TAG_IN_USE`로 막아 기록을 보존한다.
`GET /users/me/tag-summaries`의 `summary`에도 실제 최신 요약을 반환한다.

## 로컬 검증

Spring 통합 테스트는 별도 PostgreSQL·Mailpit 컨테이너에서 실제 SMTP 수신,
토큰 검증·재발급·동시 수락·트랜잭션 롤백, 요약 생성부터 투표·확정·과거 요약 보존을 검증한다.
Python 테스트는 기존 경로가 DB 접근 없이 410을 반환하는지 확인한다.
실행 명령은 [Spring README](../spring/vertical-slice/README.md)의 로컬 검증 절차를 따른다.
