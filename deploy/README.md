# 로컬 실행과 검증

현재 구성은 모든 업무 HTTP API와 마이그레이션을 Spring에서 실행한다. FastAPI는 WebSocket relay와 내부 진단만 제공한다.

- 평소 로컬 사용: `local-app.compose.yml`, 앱 `http://localhost:3000`, API `http://localhost:18000`. `start-local.ps1` / `stop-local.ps1` 또는 루트 README의 Linux 절차를 사용한다. 영속 볼륨과 `.env.local`을 보관한다.
- 개발: 루트 `docker-compose.yml`. 실제 AI 자격 증명은 Spring에만 전달한다.
- 통합 검증: `spring-workspace.compose.yml`, `http://localhost:18180`. 전용 DB·계정·모의 provider를 사용한다. 개인 데이터 볼륨은 연결하지 않는다.

명령과 이전 제약은 [Spring 작업 공간 통합](../docs/migration/spring-workspace.md)을 참고한다. `/docs`는 더 이상 제공하지 않는다.

`local-validation.compose.yml`, `verify-local.ps1`, `set-canary.ps1`과 canary routing 파일은 이전 양방향 런타임 비교 실험용이다. 현재 앱 배포·검증에 사용하지 않는다. 특히 FastAPI REST로 되돌리는 설정은 지원하지 않는다.
