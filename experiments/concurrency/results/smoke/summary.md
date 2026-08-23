# BrainNet concurrency experiment summary

Values are medians across repetitions. CPU and memory are peak samples per run, then medianed.

| Scenario | VUs | Implementation | RPS | p95 ms | p99 ms | failures | peak CPU | peak MiB |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| db | 10 | fastapi-async | 187.51 | 54.77 | 66.63 | 0.0000 | 17.28% | 35.1 |
| db | 10 | fastapi-current | 185.74 | 57.40 | 78.25 | 0.0000 | 19.18% | 35.6 |
| db | 10 | spring-platform | 186.28 | 57.60 | 80.01 | 0.0000 | 31.25% | 149.0 |
| db | 10 | spring-virtual | 187.04 | 55.15 | 64.46 | 0.0000 | 102.96% | 149.3 |
| io | 10 | fastapi-async | 48.88 | 206.32 | 227.16 | 0.0000 | 1.64% | 34.6 |
| io | 10 | fastapi-current | 7.78 | 2013.42 | 2245.95 | 0.0000 | 0.30% | 34.4 |
| io | 10 | spring-platform | 48.45 | 209.20 | 215.49 | 0.0000 | 29.98% | 126.7 |
| io | 10 | spring-virtual | 48.48 | 211.66 | 212.90 | 0.0000 | 10.69% | 129.4 |

## Root uniqueness row counts

| Implementation | Run | Project ID | Final rows |
|---|---:|---:|---:|
| fastapi-current | 1 | 900001 | 1 |
| fastapi-async | 1 | 900002 | 1 |
| spring-platform | 1 | 900003 | 1 |
| spring-virtual | 1 | 900004 | 1 |
