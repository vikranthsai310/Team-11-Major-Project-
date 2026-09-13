"""D2 · Order stream generator.

Arrivals follow a non-homogeneous Poisson process:

    lambda(t) = lambda_base * diurnal(hour(t)) * burst(t)

The diurnal shape is **fitted to the ``tx_count`` rhythm observed in D1**, not
invented. Cardano has a real daily activity cycle, and a homogeneous process
would erase the very pattern a congestion-aware policy is supposed to exploit
(``docs/05-DATA-SPEC.md`` §D2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from batcher.build.estimator import ORDER_MEM, ORDER_SIZE_B, ORDER_STEPS
from batcher.config.params import ORDER_TTL_SLOTS
from batcher.queue.manager import Order

HOURS = 24

# Named arrival-rate configurations (P2-6). Results are reported across all three;
# a policy tuned to one rate that collapses at another is a weak result, and the
# evaluation is designed to expose that.
ARRIVAL_RATES = {"light": 0.5, "matched": 1.0, "heavy": 2.0}


BLOCKS_PER_DAY = 4_320


@dataclass(frozen=True)
class ArrivalProcess:
    """Fitted arrival intensity. Everything needed to regenerate a stream exactly."""

    base_per_slot: float
    diurnal: tuple[float, ...]
    # Expressed as onsets per day rather than as a per-block probability. A
    # per-block probability has to be read against the burst *duration* to mean
    # anything: at p=0.02 per block with hour-long bursts, a new burst starts
    # every ~50 blocks while each lasts ~180, so the stream is in burst ~78 % of
    # the time and the "base" rate is never observed. That inflated arrivals 4.5x
    # and was mistaken for a policy result.
    bursts_per_day: float = 1.0
    burst_multiplier: float = 6.0
    burst_hours: float = 1.0

    @property
    def burst_probability_per_block(self) -> float:
        return self.bursts_per_day / BLOCKS_PER_DAY

    def intensity(self, hour: int) -> float:
        return self.base_per_slot * self.diurnal[hour % HOURS]

    def to_manifest(self) -> dict:
        return {
            "base_per_slot": self.base_per_slot,
            "diurnal": list(self.diurnal),
            "bursts_per_day": self.bursts_per_day,
            "burst_multiplier": self.burst_multiplier,
            "burst_hours": self.burst_hours,
            "expected_burst_share": self.burst_hours * self.bursts_per_day / 24,
        }


def fit_arrival_process(
    frame: pd.DataFrame, orders_per_block: float = 2.0, **kwargs
) -> ArrivalProcess:
    """Fit the diurnal shape to D1 transaction counts.

    ``orders_per_block`` sets the matched (1.0x) rate: how many swap orders arrive
    per block on average, for **one pool**. It is a modelling choice — no DEX
    publishes per-order arrival data — and is stated openly rather than tuned to a
    result. For scale, Phase 1 measured 3.76 transactions per block across the
    whole of Cardano, so a single pool drawing 2 is already generous; the heavy
    (2.0x) configuration explores the other side.
    """
    hourly = frame.groupby(frame["block_time"].dt.hour)["tx_count"].mean()
    shape = (hourly / hourly.mean()).reindex(range(HOURS)).fillna(1.0)

    mean_slot_gap = frame["slot_gap"][1:].mean()
    base_per_slot = orders_per_block / mean_slot_gap

    return ArrivalProcess(
        base_per_slot=float(base_per_slot), diurnal=tuple(float(v) for v in shape), **kwargs
    )


class OrderStream:
    """Generates arrivals for one episode. Deterministic given its generator."""

    def __init__(
        self,
        process: ArrivalProcess,
        rng: np.random.Generator,
        rate_multiplier: float = 1.0,
        episode_id: str = "ep",
    ):
        self.process = process
        self.rng = rng
        self.rate_multiplier = rate_multiplier
        self.episode_id = episode_id
        self._sequence = 0
        self._burst_until_slot = -1

    def arrivals(self, from_slot: int, to_slot: int, hour: int) -> list[Order]:
        """Orders arriving in ``(from_slot, to_slot]``."""
        span = max(0, to_slot - from_slot)
        if span == 0:
            return []

        intensity = self.process.intensity(hour) * self.rate_multiplier

        # A burst is an episode-scale event (an NFT mint, say), so it is decided
        # once and then persists, rather than being re-rolled every block.
        if to_slot > self._burst_until_slot:
            if self.rng.random() < self.process.burst_probability_per_block:
                self._burst_until_slot = to_slot + int(self.process.burst_hours * 3600)
        if to_slot <= self._burst_until_slot:
            intensity *= self.process.burst_multiplier

        count = int(self.rng.poisson(intensity * span))
        return [self._make_order(from_slot + 1 + i % span) for i in range(count)]

    def _make_order(self, slot: int) -> Order:
        # Identifiers are derived from the seeded sequence, never a UUID, so an
        # episode regenerates byte-identically (docs/08 §6).
        self._sequence += 1
        return Order(
            order_id=f"{self.episode_id}-{self._sequence:06d}",
            arrival_slot=slot,
            size_bytes=ORDER_SIZE_B,
            mem_exunits=ORDER_MEM,
            step_exunits=ORDER_STEPS,
            amount_in=int(self.rng.integers(10, 1_000) * 1_000_000),
            min_out=0,
            ttl_slot=slot + ORDER_TTL_SLOTS,
        )
