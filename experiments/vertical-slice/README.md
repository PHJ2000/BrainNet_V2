# BrainNet Java 25 + Spring vertical slice experiment

이 실험은 실제 BrainNet project/node 계약을 축소 재현하여 legacy FastAPI, 정합성을 보완한
FastAPI, Java 25 + Spring virtual thread를 비교한다. 판정 기준과 최종 결정은
`docs/adr/ADR-002-java25-spring-vertical-slice.md`에 있다.

## 정식 실행

Docker가 실행 중인 저장소 루트에서 다음을 실행한다.

```bash
experiments/vertical-slice/run-experiment.sh
```

기본값은 10/100/300 VU, 15초 warm-up, 30초 측정, 3회 반복이다. 정식 실행은 약 20분이
걸리며 마지막에 성능 분석, root/version 경쟁, 진단 계약과 field mutation을 실행한다.

짧은 파이프라인 검사는 다음과 같다.

```bash
REPETITIONS=1 VUS_LEVELS=10 WARMUP_DURATION=2s DURATION=5s \
  experiments/vertical-slice/run-experiment.sh
```

특정 구현의 성능만 다시 실행하려면 해당 `results/raw/load_*.json`과 대응 stats를 별도 보관한
뒤 다음 환경 변수를 사용한다.

```bash
IMPLEMENTATIONS='fastapi-safe spring' SKIP_POST=true \
  experiments/vertical-slice/run-experiment.sh
```

실행기는 이미 존재하는 raw load 결과를 건너뛴다. 사전 기준을 넘은 k6 run도 원본을 보존하고
다음 조합을 계속 실행한다.

## 별도 검사

```bash
python3 experiments/vertical-slice/diagnostics.py
bash experiments/vertical-slice/mutation/run-mutation.sh
python3 experiments/vertical-slice/verify-routing.py
python3 experiments/vertical-slice/analyze.py
```

최종 결과는 `results/summary.md`, 반복별 값은 `results/load-results.csv`, k6 원본은
`results/raw/`, 1초 자원 표본은 `results/stats/`에 있다. 프로토콜 보정 전 원본은
`results/protocol-corrections/`, 최초 파이프라인 스모크는 `results-smoke-20260820/`에 있다.

