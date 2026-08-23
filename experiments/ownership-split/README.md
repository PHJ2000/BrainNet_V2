# ADR-004 reproducible experiment

실제 BrainNet의 `POST /projects/{project_id}/nodes` AI 분기를 재현해 provider 대기와 GHOST node DB
저장을 함께 측정한다.

```bash
./run-experiment.sh
```

빠른 검사는 다음과 같다.

```bash
DURATION=2 REPETITIONS=1 LEVELS="10" RESULTS_DIR=results-smoke ./run-experiment.sh
```

기본 실행은 10/100/300 concurrency를 각 10초, 3회 측정하고 계약·장애·DB atomicity 및 nginx
cutover/rollback을 검사한다. 실제 OpenAI API는 호출하지 않는다.

최종 결과는 `results/final-report.md`, 기계 판정은 `results/gate-verification.json`에서 확인한다.
