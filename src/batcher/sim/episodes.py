"""Paired-episode construction (P2-14).

Episode *i* presents an **identical D1 window and an identical order stream** to
every policy. Differences in results are therefore attributable to the decision
logic rather than to sampling noise, which is what makes the paired statistics in
``docs/09-EVALUATION-PROTOCOL.md`` valid.

Episode selection is fixed up front and cannot be revised after seeing results.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from batcher.config.params import DEFAULT_SEED
from batcher.data.features import Split, chronological_split
from batcher.sim.orders import ARRIVAL_RATES, ArrivalProcess, OrderStream

BLOCKS_PER_EPISODE = 4_300  # about one day


@dataclass(frozen=True)
class Episode:
    """One replay window. The seed is the episode's identity, not a run detail."""

    episode_id: str
    start_index: int
    end_index: int
    seed: int

    def blocks(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame.iloc[self.start_index : self.end_index]

    def stream(self, process: ArrivalProcess, rate: str) -> OrderStream:
        return OrderStream(
            process=process,
            rng=np.random.default_rng(self.seed),
            rate_multiplier=ARRIVAL_RATES[rate],
            episode_id=self.episode_id,
        )

    def rng(self) -> np.random.Generator:
        # A separate stream from the order generator's, so that changing one
        # does not silently shift the other.
        return np.random.default_rng(self.seed + 1_000_000)


def build_episodes(
    frame: pd.DataFrame,
    split: Split | None = None,
    which: str = "train",
    count: int = 100,
    seed: int = DEFAULT_SEED,
    blocks_per_episode: int = BLOCKS_PER_EPISODE,
    congested_share: float = 0.25,
) -> list[Episode]:
    """Fixed episode set for one split.

    ``congested_share`` reserves part of the set for the busiest windows. Phase 1
    measured congested blocks concentrating into a handful of days — 64 % fall in
    the busiest five of 93 — so a uniformly sampled set would almost never contain
    congestion and every result would describe an empty chain (`adr/ADR-008`,
    risk R13). The share is fixed here, before any result is seen, and is
    reported with the results.
    """
    split = split or chronological_split(frame)
    labels = split.label(frame["abs_slot"])
    subset = frame[labels == which]

    if len(subset) < blocks_per_episode + 1:
        raise ValueError(f"{which} split holds {len(subset)} blocks; too few for an episode")

    offset = int(np.flatnonzero((labels == which).to_numpy())[0])
    last_start = len(subset) - blocks_per_episode

    rng = np.random.default_rng(seed)
    n_congested = int(count * congested_share)

    starts = list(_congested_starts(subset, blocks_per_episode, n_congested))
    while len(starts) < count:
        starts.append(int(rng.integers(0, last_start + 1)))

    return [
        Episode(
            episode_id=f"{which}-{index:03d}",
            start_index=offset + start,
            end_index=offset + start + blocks_per_episode,
            seed=seed + index,
        )
        for index, start in enumerate(starts[:count])
    ]


def _congested_starts(subset: pd.DataFrame, window: int, wanted: int) -> list[int]:
    """Window start indices centred on the densest congestion in the split."""
    if wanted <= 0:
        return []

    congested = (subset["fill_pct"] > 0.80).to_numpy().astype("int32")
    density = pd.Series(congested).rolling(window, min_periods=window).sum().to_numpy()
    order = np.argsort(-np.nan_to_num(density, nan=-1.0))

    starts: list[int] = []
    for end in order:
        start = int(end) - window + 1
        if start < 0:
            continue
        # Keep the chosen windows disjoint, or "25 % congested" collapses into
        # the same day repeated.
        if any(abs(start - chosen) < window for chosen in starts):
            continue
        starts.append(start)
        if len(starts) == wanted:
            break
    return starts
