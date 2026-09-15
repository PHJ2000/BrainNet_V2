# 노드 작업 기록과 실행 취소 (#8)

평소 로컬 앱인 FastAPI writer에 적용한다. Spring 비교용 생성 경로와 AI 생성은 이력 생성 대상에서 제외한다. 기존 데이터의 과거 기록을 추정해 채우지 않는다. 프로젝트 생성 시 자동 루트, 활성화/비활성화, 태그 자체의 편집과 프로젝트 삭제도 이번 undo 범위 밖이다.

## 기록 단위와 저장

별도 `node_operation`에 확정된 일반 생성·본문/위치 PATCH·가지 DELETE를 기록한다. 노드 외래키가 없어 대상 삭제 뒤에도 남는다. 기존 `node_version`은 내용만 담고 삭제 CASCADE되므로 복구의 저장소로 쓰지 않는다. dragfree 저장 하나가 작업 하나이며 키보드 입력기의 Ctrl+Z는 가로채지 않는다.

삭제 스냅샷은 전체 자손의 본문·상태·부모 관계·좌표·정렬·작성자·시각·version, tag_node, node_metrics, 기존 node_version을 보존한다. 태그 정의와 외부 부모 version은 복구 전제 조건으로 남긴다. vote는 tag_summary를 참조하며 노드 삭제로 제거되지 않으므로 복제하지 않는다. Outbox와 기존 생성 claim도 복제하지 않는다.

복구는 새 작업이며 원본 노드 ID를 복원하고 version을 삭제 직전 값보다 1 높인다. 갱신 취소도 현재 version + 1이다. 기록·변경·Outbox·멱등 응답은 같은 트랜잭션에 저장한다. 생성은 기존 FastAPI/Spring 공통 생성 claim을 계속 사용한다. PATCH/DELETE/undo의 멱등성 키는 사용자·프로젝트 범위에서 요청 내용과 묶인다. 각 별도 작업에는 새 키를, 불확실한 응답 재시도에는 같은 키를 사용한다.

## API와 충돌

- `GET /projects/{id}/operations?limit=50&before={operation_id}`: 최신 기록부터 페이지 조회. 다른 사람의 작업, 취소 완료, 보존 만료 여부를 표시한다.
- `GET /projects/{id}/operations/{operation_id}/preview`: 자기 작업의 현재 복구 가능성을 검사하고 before/after와 preview_hash를 반환한다.
- `POST /projects/{id}/operations/{operation_id}/undo`: Idempotency-Key 및 preview_hash 필요. 같은 요청은 최초 응답을 재사용한다.
- `GET /projects/{id}/nodes/{node_id}/delete-preview`: 범위/건수/expected_version/scope_hash 반환.
- `DELETE /projects/{id}/nodes/{node_id}?expected_version=…&scope_hash=…`: 새 UI는 미리보기의 값을 전달한다. 이전 클라이언트 호환을 위해 생략한 DELETE도 원래 동작을 유지하되 이력을 기록한다.

본문/위치 복구는 대상 version과 관련 스냅샷이 일치해야 한다. 생성 취소는 후속 수정·자손·첨부 데이터가 없어야 한다. 삭제 복구는 ID 미사용, 원 부모/작성자 생존, 부모 version, 태그 정의 일치, ACTIVE 루트 유일성이 필요하다. 서로 충돌하면 전체 실패한다. 일부 자손이나 태그만 복구하지 않는다. 기존 PATCH 응답 형식도 유지하며 완전한 태그 정보는 노드 재조회와 이력에서 제공한다.

프로젝트 접근 권한은 서버에서 확인하고 자기 작업만 되돌린다. 403은 권한, 404는 없는 기록/대상, 409는 충돌/이미 취소, 410은 만료다. 기존 데이터에는 이력이 없으므로 새 작업부터 복구 가능하다. 프로젝트 삭제 복구와 Redo는 지원하지 않는다.

## 보존·마이그레이션·검증

기본 복구/재요청 기간은 30일이다. 만료 뒤 복구를 거절하고 60초 주기 Outbox 정리에서 한 번에 최대 1,000개 기록의 payload를 지운다. metadata와 만료 표시는 남긴다. 실행 중인 기록은 SKIP LOCKED로 건너뛴다. 이벤트 worker를 꺼두면 물리 정리는 지연되지만 만료 검사는 계속 적용한다.

Alembic `b810001`은 새 테이블/인덱스만 추가한다. downgrade는 작업 기록을 없애므로 이미 사용자 기록이 쌓인 DB에서는 파일/DB 백업 없이 downgrade하지 않는다.

전용 PostgreSQL 테스트는 작업/복구 버전, 중복 요청, 동시 취소, 타인 수정 충돌, 자손 변경, 태그 유실, 관련 행 복원, 만료 정리, rollback을 검사한다. Chromium은 두 화면의 미리보기·취소·삭제 복구와 응답 유실 재시도·재접속을 검사한다. 실행 결과는 별도 검증 보고서에 기록하며 테스트 코드가 있다는 이유만으로 통과를 주장하지 않는다.
