# BrainNet vertical slice experiment summary

Medians across three runs.

| VUs | Implementation | RPS | p95 ms | p99 ms | failures | peak CPU | peak MiB | DB connections |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 10 | fastapi-legacy | 324.01 | 90.39 | 103.65 | 0.0000 | 95.85% | 54.7 | 14 |
| 10 | fastapi-safe | 256.50 | 81.30 | 100.90 | 0.0000 | 93.47% | 54.9 | 23 |
| 10 | spring | 586.99 | 47.10 | 64.57 | 0.0000 | 216.84% | 154.8 | 33 |

## Correctness

| Test | Implementation | Run | success | conflict | unexpected | state |
|---|---|---:|---:|---:|---:|---|
| root | fastapi-legacy | 1 | 8 | 92 | 0 | roots=8, nodes=8, max_version=0 |
| version | fastapi-legacy | 1 | 100 | 0 | 0 | roots=1, nodes=2, max_version=100 |
| root | fastapi-safe | 1 | 1 | 99 | 0 | roots=1, nodes=1, max_version=0 |
| version | fastapi-safe | 1 | 1 | 99 | 0 | roots=1, nodes=2, max_version=1 |
| root | spring | 1 | 0 | 0 | 100 | roots=0, nodes=0, max_version=0 |
| version | spring | 1 | 1 | 99 | 0 | roots=1, nodes=2, max_version=1 |
