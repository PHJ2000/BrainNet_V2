# 고부하 수정 검증 원본

구현은 `2adbcc1`, 실행 이미지와 자원 설정은 `run-config.json`을 따른다. 실제 OpenAI 호출은 없다. 행렬 24회, 비교 기준 6회, 엄격한 1시간 검증과 컨테이너 정리는 완료됐으며 최종 상태는 `completion.json`의 `PASSED`다.

해당 검증의 자동 후처리는 `experiments/runtime-nodes/finish-validation.ps1`이 맡았다. `STATUS.txt`에 진행 상태와 최종 PASSED/FAILED를 쓰고, 검증 종료 뒤 집계·보고서 갱신·해당 Compose 프로젝트의 컨테이너와 볼륨 정리를 수행한다. 실패해도 JSON과 로그를 남기며 통과로 바꾸지 않는다. `completion.json`은 최종 검증과 정리 결과다. 잠금 파일로 중복 실행을 막고, 기다리는 시간은 기본 3,300초로 제한한다.

전체 실행은 `experiments/runtime-nodes/run-validation-background.ps1`이 담당한다. 별도 DB를 만들고 고정된 이미지에서 1시간 검증과 자원 수집을 시작하며, 직접 시작한 프로세스의 종료 핸들을 확인한 뒤 후처리를 호출한다. `soak-interrupted-automation/`은 처음 붙인 감시 스크립트의 종료 판정 오류로 23분에 중단된 기록이며, 최종 통과 결과에 포함하지 않는다.

`soak-startup-failed/`은 DB 준비 전에 `createdb`를 실행한 초기 자동화의 실패 기록이다. 실행기에 Compose의 DB health 대기를 적용한 뒤 새 검증을 시작했다.

- `matrix/`: 수정 후 일반·AI C100/C300, 런타임 2개, 60초 × 3회. 4개 발생기 프로세스와 풀당 최대 20개 요청을 사용한다. `resources.jsonl`은 이 행렬의 자원 표본이다.
- `baseline/`: 같은 이미지·발생기·DB에서 FastAPI 동시 실행 한도를 측정 부하보다 크게 설정해 제한 효과를 비교한다. 일반·AI C300, 60초 × 3회. 실패 회차도 포함한다.
- `soak/`: 3,600초, 100개 WebSocket, 초당 5개 논리 작업의 엄격한 검증. 개별 접속자의 생성·삭제 이벤트 수까지 대조한다.
- `local-app.json`: 별도 로컬 앱의 브라우저 기능 확인, 컨테이너 재생성 후 데이터 보존, health check와 포트 바인딩 결과. 부하 측정과 별도다.
- `diagnostic/`: 짧은 원인 조사 회차와 CPU 프로파일의 상위 함수 집계. `sharded`는 한 프로세스 내 풀 분할, `asgi`와 `provider-pool`은 채택하지 않은 후보, `stages`는 대기 구간 계측, `gate32`는 추가 동시 실행 제한이다. 계측 오버헤드가 있으므로 본 측정의 대표 수치로 사용하지 않는다. 초기 regular 단계 계측은 asyncio loop를 사용했고, 후속 AI 단계 계측은 실제 실행과 같은 uvloop를 사용했다.
- `single-process/`: 풀을 나눈 뒤에도 Spring 발생기 한 코어가 약 91% 사용된 완료 회차 4개. 그 뒤의 준비 요청 중 조사를 종료했고, 미완료 claim 0개를 확인한 뒤 새 측정을 시작했다. 최종 행렬에서 제외한다.
- `multiprocess-smoke/`: 4개 프로세스 발생기의 C300 일반 생성 20초 확인 회차 2개. 최종 60초 행렬에서 제외한다.
- 루트 `resources.jsonl`: 진단/준비 기간의 표본. 최종 행렬의 자원 표본과 구분한다.

`python experiments/runtime-nodes/summarize_fix.py --require-complete`로 재집계한다. 회차별 지표의 중앙값을 비교하며, 각 회차 내부에서는 발생기 프로세스의 원본 요청 지연을 합친다. 발생기 변경 전후 처리량 차이를 앱 수정 효과로 계산하지 않는다. UTC 시각은 호스트에서 조정될 수 있으므로 처리량·latency·실행 시간·수집기 종료 시한에는 monotonic clock을 사용한다.
