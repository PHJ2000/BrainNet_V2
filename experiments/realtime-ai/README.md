# ADR-003 reproducible experiment

BrainNet의 AI provider 대기, SSE streaming, project WebSocket workload를 동일한 mock provider와
동일한 container 제한에서 FastAPI와 Java 25 + Spring으로 비교한다.

## 실행

```bash
cd experiments/realtime-ai
./run-experiment.sh
```

빠른 기능 검증:

```bash
RESULTS_DIR=results-smoke AI_LEVELS="10" AI_DURATION=5 \
SSE_LEVELS="5" WS_LEVELS="10" REPETITIONS=1 SKIP_SOAK=true ./run-experiment.sh
```

기본 실행은 AI 부하 3단계, SSE, WebSocket, 장애, routing과 구현별 15분 soak를 수행한다. 실제
OpenAI API를 호출하지 않아 비용이 들지 않으며 provider의 지연과 실패를 결정적으로 재현한다.

단일-worker 효과와 process-local WebSocket fan-out을 확인하는 사후 민감도는 다음으로 재현한다.

```bash
./run-sensitivity.sh
python3 verify-results.py
```

환경 변수로 `REPETITIONS`, `AI_DURATION`, `AI_LEVELS`, `SSE_LEVELS`, `WS_LEVELS`,
`SOAK_DURATION`, `SKIP_SOAK`, `RESULTS_DIR`를 조정할 수 있다. 최종 판정에는 기본값을 사용한다.
