# BrainNet vertical slice experiment summary

Medians across three runs.

| VUs | Implementation | RPS | p95 ms | p99 ms | failures | peak CPU | peak MiB | DB connections |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 10 | fastapi-legacy | 218.73 | 86.86 | 103.77 | 0.0000 | 97.37% | 55.6 | 33 |
| 10 | fastapi-safe | 214.96 | 90.56 | 109.73 | 0.0000 | 98.91% | 55.7 | 33 |
| 10 | spring | 3389.06 | 16.98 | 33.52 | 0.0000 | 197.04% | 176.9 | 33 |
| 100 | fastapi-legacy | 307.73 | 707.27 | 1327.38 | 0.0000 | 97.78% | 61.8 | 91 |
| 100 | fastapi-safe | 182.99 | 1147.38 | 1652.42 | 0.0000 | 98.82% | 62.0 | 91 |
| 100 | spring | 3459.05 | 71.75 | 102.71 | 0.0000 | 231.61% | 230.9 | 91 |
| 300 | fastapi-legacy | 311.54 | 3446.76 | 5242.90 | 0.0107 | 97.87% | 73.4 | 62 |
| 300 | fastapi-safe | 272.34 | 4232.09 | 5336.77 | 0.0250 | 98.05% | 74.5 | 91 |
| 300 | spring | 3342.76 | 187.82 | 304.60 | 0.0000 | 234.37% | 919.0 | 62 |

## Correctness

| Test | Implementation | Run | success | conflict | unexpected | state |
|---|---|---:|---:|---:|---:|---|
| root | fastapi-legacy | 1 | 6 | 94 | 0 | roots=6, nodes=6, max_version=0 |
| version | fastapi-legacy | 1 | 100 | 0 | 0 | roots=1, nodes=2, max_version=100 |
| root | fastapi-legacy | 2 | 18 | 82 | 0 | roots=18, nodes=18, max_version=0 |
| version | fastapi-legacy | 2 | 100 | 0 | 0 | roots=1, nodes=2, max_version=100 |
| root | fastapi-legacy | 3 | 29 | 71 | 0 | roots=29, nodes=29, max_version=0 |
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
