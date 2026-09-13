from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from batcher.data.sources import BlockRecord

REPO_ROOT = Path(__file__).resolve().parents[1]

# A plausible starting point on mainnet; nothing depends on the exact values.
BASE_HEIGHT = 13_900_000
BASE_SLOT = 197_600_000
BASE_TIME = 1_789_000_000


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def src_root() -> Path:
    return REPO_ROOT / "src" / "batcher"


def make_records(n: int, seed: int = 0, skip: set[int] | None = None) -> list[BlockRecord]:
    """Synthetic blocks with a realistic geometric slot cadence, ascending by height.

    ``skip`` removes heights to simulate a collection gap.
    """
    rng = np.random.default_rng(seed)
    skip = skip or set()
    records = []
    slot = BASE_SLOT

    for index in range(n):
        height = BASE_HEIGHT + index
        slot += int(rng.geometric(0.05))
        if height in skip:
            continue
        records.append(
            BlockRecord(
                block_height=height,
                abs_slot=slot,
                block_time=BASE_TIME + (slot - BASE_SLOT),
                block_size=int(rng.integers(4, 90_112)),
                tx_count=int(rng.integers(0, 60)),
                epoch_no=655 + (slot - BASE_SLOT) // 432_000,
                block_hash=f"{height:064x}",
            )
        )
    return records


class FakeSource:
    """In-memory BlockSource. Counts pages so resumability can be asserted."""

    name = "fake"

    def __init__(self, records: list[BlockRecord]):
        self.by_height = {record.block_height: record for record in records}
        self.pages_served = 0

    def tip_height(self) -> int:
        return max(self.by_height)

    def blocks_at_or_below(self, max_height: int, limit: int) -> list[BlockRecord]:
        self.pages_served += 1
        heights = sorted((h for h in self.by_height if h <= max_height), reverse=True)
        return [self.by_height[h] for h in heights[:limit]]


@pytest.fixture
def records() -> list[BlockRecord]:
    return make_records(250)


@pytest.fixture
def source(records) -> FakeSource:
    return FakeSource(records)
