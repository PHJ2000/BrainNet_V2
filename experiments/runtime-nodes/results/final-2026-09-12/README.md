# 결과 구분

- `matrix/`: 후속 구현의 일반 C10/C100 12회. 같은 호스트·PostgreSQL에서 별도 DB soak 동시 실행. `fastapi-regular-c300-run1-failed.json`은 측정기 중단을 일으킨 최초 고부하 실패이며 집계 36회에서 제외했다.
- `isolated/`: soak 종료 후 일반 C300 6회와 AI C10/C100/C300 18회. 성공 응답과 timeout 후 commit을 구분해 DB 결과 대조. 지연·오류 기준에 미달한 회차도 포함한다.
- `pool-reuse/`: 미채택 후보(`pool_size=30, max_overflow=0`) 6회. 최종 코드는 원래 `10, 20` 설정으로 복구했다. 정규 36회 합계에서 제외한다.
- `soak-verified/`: 1시간 검증 원본. 폴더명은 실행 시 정한 이름일 뿐 **통과를 뜻하지 않는다**. 18,000개 중 6개 실패. `recovery.json`은 이후 같은 키로 중복 없이 복구한 별도 증거다.
- 루트 `soak.json`, `soak-resources.jsonl`: Java provider HTTP/2 문제 수정 전 중단한 첫 시도. 통과 결과가 아니다.
- `summary.json`: `summarize.py`로 만든 회차별 중앙값과 비교 결과. `npm-audit.json`: 최종 의존성 검사.

부하의 시간 분모와 지연은 monotonic clock이다. Windows/Docker 환경의 UTC 시계 보정으로 일부 wall-clock timestamp는 역전돼 있어 UTC 차이로 RPS를 재계산하지 않는다. `monitoring`은 연결 수·대기 분류 표본이며 SQL별 wait 시간 누계가 아니다. 리소스의 MemUsage는 Docker 컨테이너 메모리 지표이며 프로세스 RSS와 같지 않다.

종합 판단과 통과하지 못한 조건은 [최종 보고서](../../../../docs/REFACTORING_COMPLETION_2026-09-12.md)를 따른다. 실제 OpenAI·외부 운영 환경 성능을 입증하는 결과가 아니다.
