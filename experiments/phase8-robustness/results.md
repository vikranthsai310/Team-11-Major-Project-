# Phase 8 · Robustness of the runtime shields (validation split)

10 paired validation episodes per rate; medians across episodes. Forecaster: LightGBM. `l_p95_all` counts each expired order's wait until expiry (a lower bound). `overshoot` = oldest wait at submission minus D_MAX=120, per-episode maximum. `late` = share of settled orders with latency > D_MAX. Cost is lovelace per user.

| rate | policy | L-p95 | L-p95 all | submit wait max | overshoot (med / max) | late | X-rate (med / max) | C-user | interventions (med / total) |
|---|---|---|---|---|---|---|---|---|---|
| matched | p2(N=4) | 127.0 | 127.0 | 204 | 84 / 152 | 0.063 | 0.000 / 0.000 | 127,469 | – / – |
| matched | deadline(p2(N=4)) | 123.0 | 123.0 | 188 | 68 / 152 | 0.055 | 0.000 / 0.000 | 137,756 | 316 / 3,608 |
| matched | p3(dqn seed3) | 161.5 | 161.5 | 238 | 118 / 3,480 | 0.211 | 0.000 / 0.270 | 90,944 | – / – |
| matched | p3(dqn seed3)+largest-repair | 137.0 | 137.0 | 220 | 100 / 201 | 0.086 | 0.000 / 0.000 | 144,364 | – / – |
| matched | shield(p3(dqn seed3), p2(N=4)) | 154.0 | 154.0 | 232 | 112 / 152 | 0.171 | 0.000 / 0.000 | 88,781 | 487 / 4,878 |
| heavy | p2(N=4) | 245.5 | 245.5 | 420 | 300 / 1,001 | 0.164 | 0.000 / 0.000 | 100,662 | – / – |
| heavy | deadline(p2(N=4)) | 245.5 | 245.5 | 420 | 300 / 1,001 | 0.163 | 0.000 / 0.000 | 101,751 | 58 / 675 |
| heavy | p3(dqn seed3) | 3,605.0 | 3,600.0 | 3,600 | 3,480 / 3,480 | 0.206 | 0.357 / 0.586 | 116,445 | – / – |
| heavy | p3(dqn seed3)+largest-repair | 255.0 | 255.0 | 423 | 303 / 1,042 | 0.182 | 0.000 / 0.000 | 106,861 | – / – |
| heavy | shield(p3(dqn seed3), p2(N=4)) | 245.5 | 245.5 | 422 | 302 / 1,001 | 0.205 | 0.000 / 0.000 | 79,487 | 375 / 4,114 |

## Notes

- Split: `val` (the test split is not opened). Episode set: build_episodes(seed=42), the same construction Phase 6 used, on validation.
- P2 runs through the simulator (rollbacks modelled); DQN variants run through the Gym env, as Phase 6 did (no rollbacks). Compare within a family.
- DeadlineAwarePolicy: p90 of observed block gaps + p90 of observed confirmation delays, learned online per episode (priors 46 + 46 slots before 20 samples). Its `interventions` are deadline-pressure submissions.
