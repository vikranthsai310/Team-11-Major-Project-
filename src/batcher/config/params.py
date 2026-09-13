"""Project tunables — values we choose, as opposed to values the ledger imposes.

Nothing here is a protocol parameter; protocol parameters live in
``batcher.config.protocol`` and may not be duplicated. Everything here is a
design choice that gets **tuned on the validation split** and disclosed in the
results table (``docs/09-EVALUATION-PROTOCOL.md``). Each entry records the phase
in which its final value is fixed.

An untuned knob reported as if it were principled is a straw man; an undisclosed
one invalidates the comparison. Both are why this module exists.
"""

# --- Policy deadlines and thresholds ---

# Hard starvation deadline. Once the oldest queued order has waited this long,
# WAIT is masked by the environment and submission is forced (invariant I2).
D_MAX = 120  # slots (~2 min)  # tuned: Phase 4 (P4-2)

# Batch size below which waiting for more orders may be worthwhile. Seeded from
# the knee of the amortization curve (docs/07 §5), which flattens near n ~ 10 —
# not from a guess. Justify the final value from figure F3.
N_MIN = 8  # orders  # tuned: Phase 4 (P4-2)

# --- Forecasting ---

# Rolling window of the E4 moving-average baseline: fill_hat(t+1) = mean(last k).
FORECAST_WINDOW_K = 20  # blocks  # tuned: Phase 3 (P3-1)

# Number of future blocks the forecaster emits and the policy may consult.
FORECAST_HORIZON = 3  # blocks t+1..t+3  # tuned: Phase 4 (P4-2)

# --- Queue and mempool ---

# Validity interval applied to a submitted batch: ttl = current_slot + TTL_SLOTS.
# On expiry the pool unlocks and the orders return to the queue (docs/04 M5).
TTL_SLOTS = 600  # slots (~10 min)  # tuned: Phase 2 (P2-7)

# Lifetime of an individual user order in the queue before it is evicted and
# counted as an expiry (metric X-rate).
ORDER_TTL_SLOTS = 3_600  # slots (~1 h)  # tuned: Phase 2 (P2-5)

# Normalisation ceiling for queue depth in the RL state vector (docs/06 §5), and
# nothing else. It is **not** an admission cap: an order is a UTXO already sitting
# at the script address, so the batcher discovers it rather than admitting it and
# has no mechanism to refuse one. The queue is unbounded.
QUEUE_CAP = 200  # orders  # tuned: Phase 5 (P5-2)

# --- RL action space ---

# Discrete SUBMIT(n) choices offered to the agent, in addition to WAIT. The
# Gate A maximum feasible n is appended at runtime (it depends on the live queue
# contents, so it cannot be a constant) and every bucket is clamped to it.
ACTION_BUCKETS = (1, 4, 8, 12, 16, 20, 25, 30)  # tuned: Phase 5 (P5-3)

# --- Reproducibility ---

DEFAULT_SEED = 42
