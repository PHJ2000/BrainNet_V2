# ADR-003 experiment summary

Median of repeated runs.

| Workload | concurrency | Implementation | RPS | p95 ms | failure | peak CPU | peak MiB |
|---|---:|---|---:|---:|---:|---:|---:|
| ai | 10 | fastapi-legacy | 4.81 | 2101.40 | 0.0000 | 1.78% | 38.4 |
| ai | 10 | fastapi-safe | 47.16 | 224.10 | 0.0000 | 27.67% | 41.1 |
| ai | 10 | spring | 48.03 | 213.81 | 0.0000 | 52.84% | 166.5 |
| ai | 100 | fastapi-legacy | 16.04 | 6005.06 | 0.9345 | 2.29% | 41.0 |
| ai | 100 | fastapi-safe | 65.09 | 4924.04 | 0.0121 | 92.39% | 47.0 |
| ai | 100 | spring | 483.47 | 213.83 | 0.0000 | 77.51% | 287.7 |
| ai | 300 | fastapi-legacy | 46.94 | 6138.20 | 0.9785 | 7.02% | 43.0 |
| ai | 300 | fastapi-safe | 53.57 | 6027.43 | 0.7755 | 98.47% | 70.0 |
| ai | 300 | spring | 557.00 | 764.50 | 0.0000 | 122.15% | 629.0 |
| sse | 20 | fastapi-safe | 0.00 | 365.36 | 0.0000 | 16.01% | 69.0 |
| sse | 20 | spring | 0.00 | 133.22 | 0.0000 | 0.12% | 622.5 |
| sse | 100 | fastapi-safe | 0.00 | 698.84 | 0.0000 | 61.67% | 66.9 |
| sse | 100 | spring | 0.00 | 265.02 | 0.0000 | 0.03% | 623.7 |
| ws | 100 | fastapi-safe | 0.00 | 15.40 | 0.0000 | 0.18% | 66.9 |
| ws | 100 | spring | 0.00 | 39.22 | 0.0000 | 41.42% | 626.0 |
| ws | 500 | fastapi-safe | 0.00 | 58.42 | 0.0000 | 74.46% | 69.6 |
| ws | 500 | spring | 0.00 | 152.46 | 0.0000 | 73.52% | 630.1 |

## Fault probes

- `faults_fastapi-safe`: pass=`True`, 503→`502`, timeout→`504`, recovery→`200`
- `faults_spring`: pass=`True`, 503→`502`, timeout→`504`, recovery→`200`

## Soak

| Implementation | duration | failure | restart | RSS first segment | RSS last segment | growth |
|---|---:|---:|---:|---:|---:|---:|
| fastapi-safe | 902.4s | 0.0018 | 0 | 67.2 MiB | 67.2 MiB | 0.0% |
| spring | 900.9s | 0.0000 | 0 | 634.3 MiB | 635.0 MiB | 0.1% |
