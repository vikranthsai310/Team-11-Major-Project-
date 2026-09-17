# Phase 8 · Transaction chaining (validation split)

10 validation episodes per rate, `build_episodes(seed=42)`, forecaster: LightGBM. Medians over episodes. Depth 1 is the recorded simulator.

| rate | policy | depth | L-p95 | L-p95 all | late share | overshoot | X-rate | C-user | throughput | batches/decision block |
|---|---|---|---|---|---|---|---|---|---|---|
| matched | p2(N=4) | 1 | 127.0 | 127.0 | 0.063 | 84 | 0.000 | 127,469 | 116.2 | 1.00 |
| matched | e3(greedy) | 1 | 120.0 | 120.0 | 0.049 | 68 | 0.000 | 160,439 | 116.3 | 1.00 |
| matched | p2(N=4) | 2 | 124.5 | 124.5 | 0.057 | 84 | 0.000 | 127,537 | 116.2 | 1.01 |
| matched | e3(greedy) | 2 | 116.5 | 116.5 | 0.043 | 65 | 0.000 | 161,039 | 116.3 | 1.01 |
| matched | p2(N=4) | 3 | 124.5 | 124.5 | 0.057 | 84 | 0.000 | 127,537 | 116.2 | 1.01 |
| matched | e3(greedy) | 3 | 116.0 | 116.0 | 0.043 | 65 | 0.000 | 161,074 | 116.3 | 1.01 |
| heavy | p2(N=4) | 1 | 245.5 | 245.5 | 0.164 | 300 | 0.000 | 100,662 | 249.3 | 1.00 |
| heavy | e3(greedy) | 1 | 245.0 | 245.0 | 0.162 | 300 | 0.000 | 114,365 | 249.3 | 1.00 |
| heavy | p2(N=4) | 2 | 120.0 | 120.0 | 0.050 | 96 | 0.000 | 101,868 | 249.3 | 1.04 |
| heavy | e3(greedy) | 2 | 118.0 | 118.0 | 0.046 | 90 | 0.000 | 116,166 | 249.3 | 1.03 |
| heavy | p2(N=4) | 3 | 113.0 | 113.0 | 0.037 | 96 | 0.000 | 102,061 | 249.3 | 1.04 |
| heavy | e3(greedy) | 3 | 111.0 | 111.0 | 0.034 | 90 | 0.000 | 116,510 | 249.3 | 1.04 |
