"""Cardano protocol parameters — the single source of truth for this project.

These values are **governance-changeable configuration**, not immutable literals.
They are collected here so that a protocol parameter update is a one-file change
and so that no analysis, policy or simulator module can silently disagree with
another about what the ledger permits.

Source of record: ``docs/07-CONSTRAINTS-COST-MODEL.md`` §1.

NFR-4 is enforced by ``tests/test_protocol_constants.py``: these literals may not
appear anywhere else under ``src/``.
"""

# --- Per-transaction capacity (Gate A — feasibility, congestion independent) ---
MAX_TX_SIZE = 16_384
MAX_TX_EX_MEM = 14_000_000
MAX_TX_EX_STEPS = 10_000_000_000

# --- Per-block capacity (Gate B — inclusion, congestion dependent) ---
MAX_BLOCK_SIZE = 90_112
MAX_BLOCK_EX_MEM = 62_000_000
MAX_BLOCK_EX_STEPS = 40_000_000_000

# --- Fee model: fee = MIN_FEE_A*size + MIN_FEE_B + PRICE_MEM*mem + PRICE_STEPS*steps ---
MIN_FEE_A = 44
MIN_FEE_B = 155_381
PRICE_MEM = 0.0577
PRICE_STEPS = 0.0000721

# --- Chain cadence ---
SLOT_SECONDS = 1
ACTIVE_SLOT_COEFF = 0.05
