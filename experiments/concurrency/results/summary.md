# BrainNet concurrency experiment summary

Values are medians across repetitions. CPU and memory are peak samples per run, then medianed.

| Scenario | VUs | Implementation | RPS | p95 ms | p99 ms | failures | peak CPU | peak MiB |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| db | 10 | fastapi-async | 188.06 | 54.36 | 69.70 | 0.0000 | 20.94% | 35.6 |
| db | 10 | fastapi-current | 183.08 | 54.14 | 69.52 | 0.0000 | 20.44% | 34.2 |
| db | 10 | spring-platform | 191.96 | 53.67 | 66.95 | 0.0000 | 17.24% | 166.5 |
| db | 10 | spring-virtual | 191.63 | 53.07 | 67.13 | 0.0000 | 33.43% | 165.2 |
| db | 100 | fastapi-async | 545.22 | 320.43 | 656.03 | 0.0000 | 95.77% | 39.2 |
| db | 100 | fastapi-current | 526.58 | 311.37 | 672.80 | 0.0000 | 90.94% | 37.0 |
| db | 100 | spring-platform | 585.02 | 192.51 | 291.72 | 0.0000 | 55.84% | 198.9 |
| db | 100 | spring-virtual | 579.91 | 219.37 | 301.10 | 0.0000 | 41.75% | 194.5 |
| db | 500 | fastapi-async | 515.32 | 1967.60 | 2805.01 | 0.0000 | 89.54% | 47.7 |
| db | 500 | fastapi-current | 491.80 | 2031.18 | 3131.43 | 0.0000 | 93.70% | 46.1 |
| db | 500 | spring-platform | 583.88 | 1129.11 | 1161.46 | 0.0000 | 38.95% | 246.4 |
| db | 500 | spring-virtual | 574.53 | 1652.15 | 1689.25 | 0.0000 | 33.67% | 439.0 |
| io | 10 | fastapi-async | 53.74 | 207.38 | 213.85 | 0.0000 | 1.78% | 34.6 |
| io | 10 | fastapi-current | 5.38 | 2073.76 | 4296.18 | 0.0000 | 0.45% | 33.2 |
| io | 10 | spring-platform | 53.63 | 208.30 | 215.20 | 0.0000 | 14.63% | 139.0 |
| io | 10 | spring-virtual | 53.70 | 208.19 | 216.83 | 0.0000 | 16.71% | 129.1 |
| io | 100 | fastapi-async | 536.74 | 208.27 | 212.99 | 0.0000 | 5.72% | 36.4 |
| io | 100 | fastapi-current | 13.48 | 10001.08 | 10001.33 | 0.6381 | 0.30% | 33.3 |
| io | 100 | spring-platform | 541.68 | 202.82 | 210.23 | 0.0000 | 16.05% | 178.9 |
| io | 100 | spring-virtual | 536.21 | 207.24 | 219.09 | 0.0000 | 17.70% | 166.8 |
| io | 500 | fastapi-async | 2666.47 | 210.73 | 224.54 | 0.0000 | 30.70% | 44.8 |
| io | 500 | fastapi-current | 52.04 | 10000.94 | 10001.24 | 0.9043 | 0.36% | 33.4 |
| io | 500 | spring-platform | 984.09 | 562.67 | 577.88 | 0.0000 | 72.18% | 226.5 |
| io | 500 | spring-virtual | 2637.96 | 216.01 | 236.48 | 0.0000 | 47.33% | 884.6 |

## Root uniqueness row counts

| Implementation | Run | Project ID | 201 | 409 | unexpected | Final rows |
|---|---:|---:|---:|---:|---:|---:|
| fastapi-current | 1 | 910001 | 1 | 99 | 0 | 1 |
| fastapi-current | 2 | 910002 | 1 | 99 | 0 | 1 |
| fastapi-current | 3 | 910003 | 1 | 99 | 0 | 1 |
| fastapi-async | 1 | 910004 | 1 | 99 | 0 | 1 |
| fastapi-async | 2 | 910005 | 1 | 99 | 0 | 1 |
| fastapi-async | 3 | 910006 | 1 | 99 | 0 | 1 |
| spring-platform | 1 | 910007 | 1 | 99 | 0 | 1 |
| spring-platform | 2 | 910008 | 1 | 99 | 0 | 1 |
| spring-platform | 3 | 910009 | 1 | 99 | 0 | 1 |
| spring-virtual | 1 | 910010 | 1 | 99 | 0 | 1 |
| spring-virtual | 2 | 910011 | 1 | 99 | 0 | 1 |
| spring-virtual | 3 | 910012 | 1 | 99 | 0 | 1 |
