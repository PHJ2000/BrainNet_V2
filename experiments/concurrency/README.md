# BrainNet concurrency experiment

This experiment compares the current blocking FastAPI call shape, corrected asynchronous
FastAPI, Spring MVC on Java 25 platform threads, and Spring MVC on Java 25 virtual threads.

The protocol and decision thresholds are preregistered in
`docs/adr/ADR-001-java25-spring-backend-migration.md`. Do not change the thresholds after
examining results; record any protocol deviation in the final report.

## Run

```bash
cd experiments/concurrency
./run-experiment.sh
```

Defaults are 15 seconds of warm-up and three 30-second measurements for each combination.
For a smoke check only:

```bash
REPETITIONS=1 WARMUP_DURATION=2s DURATION=5s ./run-experiment.sh
```

Raw k6 summaries, container-stat samples, a normalized CSV, and the generated Markdown summary
are written under `results/`.
