# BrainNet vertical slice experiment summary

Medians across three runs.

| VUs | Implementation | RPS | p95 ms | p99 ms | failures | peak CPU | peak MiB | total DB connections |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 10 | fastapi-legacy | 218.73 | 86.86 | 103.77 | 0.0000 | 97.37% | 55.6 | 33 |
| 10 | fastapi-safe | 452.27 | 49.08 | 62.46 | 0.0000 | 197.52% | 132.4 | 16 |
| 10 | spring | 3432.36 | 16.69 | 32.88 | 0.0000 | 200.67% | 208.6 | 16 |
| 100 | fastapi-legacy | 307.73 | 707.27 | 1327.38 | 0.0000 | 97.78% | 61.8 | 91 |
| 100 | fastapi-safe | 481.12 | 489.74 | 744.48 | 0.0000 | 200.41% | 140.9 | 34 |
| 100 | spring | 3618.93 | 72.72 | 102.78 | 0.0000 | 233.67% | 242.4 | 34 |
| 300 | fastapi-legacy | 311.54 | 3446.76 | 5242.90 | 0.0107 | 97.87% | 73.4 | 62 |
| 300 | fastapi-safe | 454.29 | 2220.47 | 3982.72 | 0.0051 | 201.38% | 155.3 | 34 |
| 300 | spring | 4064.93 | 168.23 | 272.59 | 0.0000 | 244.21% | 648.2 | 34 |

## Correctness

| Test | Implementation | Run | success | conflict | unexpected | state |
|---|---|---:|---:|---:|---:|---|
| root | fastapi-legacy | 1 | 1 | 99 | 0 | roots=1, nodes=1, max_version=0 |
| version | fastapi-legacy | 1 | 100 | 0 | 0 | roots=1, nodes=2, max_version=100 |
| root | fastapi-legacy | 2 | 8 | 92 | 0 | roots=8, nodes=8, max_version=0 |
| version | fastapi-legacy | 2 | 100 | 0 | 0 | roots=1, nodes=2, max_version=100 |
| root | fastapi-legacy | 3 | 14 | 86 | 0 | roots=14, nodes=14, max_version=0 |
| version | fastapi-legacy | 3 | 100 | 0 | 0 | roots=1, nodes=2, max_version=100 |
| root | fastapi-safe | 1 | 1 | 99 | 0 | roots=1, nodes=1, max_version=0 |
| version | fastapi-safe | 1 | 1 | 99 | 0 | roots=1, nodes=2, max_version=1 |
| root | fastapi-safe | 2 | 1 | 99 | 0 | roots=1, nodes=1, max_version=0 |
| version | fastapi-safe | 2 | 1 | 99 | 0 | roots=1, nodes=2, max_version=1 |
| root | fastapi-safe | 3 | 1 | 99 | 0 | roots=1, nodes=1, max_version=0 |
| version | fastapi-safe | 3 | 1 | 99 | 0 | roots=1, nodes=2, max_version=1 |
| root | spring | 1 | 1 | 99 | 0 | roots=1, nodes=1, max_version=0 |
| version | spring | 1 | 1 | 99 | 0 | roots=1, nodes=2, max_version=1 |
| root | spring | 2 | 1 | 99 | 0 | roots=1, nodes=1, max_version=0 |
| version | spring | 2 | 1 | 99 | 0 | roots=1, nodes=2, max_version=1 |
| root | spring | 3 | 1 | 99 | 0 | roots=1, nodes=1, max_version=0 |
| version | spring | 3 | 1 | 99 | 0 | roots=1, nodes=2, max_version=1 |
