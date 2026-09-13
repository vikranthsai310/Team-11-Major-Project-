"""P2-14 — the paired-episode harness.

If episodes are not identical across policies, every comparison in the report is
confounded and the paired statistics are invalid. These tests are the guard.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from batcher.config.protocol import MAX_BLOCK_SIZE
from batcher.data.collector import collect_blocks
from batcher.data.features import chronological_split, preprocess
from batcher.sim.episodes import build_episodes
from batcher.sim.orders import fit_arrival_process
from conftest import BASE_HEIGHT, FakeSource, make_records

WINDOW = 50


@pytest.fixture(scope="module")
def frame(tmp_path_factory):
    source = FakeSource(make_records(3000, seed=21))
    blocks = collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=tmp_path_factory.mktemp("staging"),
        page_size=1000,
    )
    return preprocess(blocks)


def episodes(frame, **kwargs):
    return build_episodes(
        frame,
        chronological_split(frame),
        which=kwargs.pop("which", "train"),
        count=kwargs.pop("count", 10),
        blocks_per_episode=kwargs.pop("blocks_per_episode", WINDOW),
        **kwargs,
    )


def test_every_policy_sees_an_identical_window_and_order_stream(frame):
    """The pairing property. Two policies must get the same episode, exactly."""
    episode = episodes(frame)[0]
    process = fit_arrival_process(frame, bursts_per_day=0.0)

    first = episode.stream(process, "matched")
    second = episode.stream(process, "matched")

    blocks = episode.blocks(frame)
    previous = int(blocks.iloc[0]["abs_slot"]) - 1
    for block in blocks.itertuples():
        slot = int(block.abs_slot)
        a = first.arrivals(previous, slot, block.block_time.hour)
        b = second.arrivals(previous, slot, block.block_time.hour)
        assert [o.order_id for o in a] == [o.order_id for o in b]
        assert [o.arrival_slot for o in a] == [o.arrival_slot for o in b]
        previous = slot


def test_the_episode_set_is_reproducible_from_the_seed(frame):
    assert episodes(frame, seed=7) == episodes(frame, seed=7)


def test_a_different_seed_gives_a_different_set(frame):
    assert episodes(frame, seed=1) != episodes(frame, seed=2)


def test_episodes_stay_inside_their_split(frame):
    split = chronological_split(frame)
    labels = split.label(frame["abs_slot"])

    for which in ("train", "val", "test"):
        for episode in episodes(frame, which=which):
            window = episode.blocks(frame)
            assert (labels.iloc[episode.start_index : episode.end_index] == which).all()
            assert len(window) == WINDOW


def test_episode_windows_have_the_requested_length(frame):
    for episode in episodes(frame, count=5):
        assert episode.end_index - episode.start_index == WINDOW


def test_congested_windows_are_deliberately_included(frame):
    """Phase 1 found congestion concentrating into a few days (ADR-008, R13).

    Uniform sampling would almost never contain any, so every result would
    describe an empty chain. The reserved share is fixed before results are seen.
    """
    congested = frame.copy()
    spike = slice(400, 400 + WINDOW)
    congested.iloc[spike, congested.columns.get_loc("block_size")] = int(0.95 * MAX_BLOCK_SIZE)
    congested["fill_pct"] = congested["block_size"] / MAX_BLOCK_SIZE

    with_congestion = build_episodes(
        congested,
        chronological_split(congested),
        which="train",
        count=8,
        blocks_per_episode=WINDOW,
        congested_share=0.25,
    )
    shares = [
        float((episode.blocks(congested)["fill_pct"] > 0.80).mean()) for episode in with_congestion
    ]
    assert max(shares) > 0.5, "no episode covered the congested window"


def test_no_congested_windows_when_the_share_is_zero(frame):
    plain = episodes(frame, congested_share=0.0, count=6, seed=3)
    assert len(plain) == 6


def test_congested_windows_do_not_all_land_on_the_same_day(frame):
    """Otherwise '25 % congested' collapses into one window repeated."""
    congested = frame.copy()
    congested["block_size"] = int(0.95 * MAX_BLOCK_SIZE)
    congested["fill_pct"] = congested["block_size"] / MAX_BLOCK_SIZE

    chosen = build_episodes(
        congested,
        chronological_split(congested),
        which="train",
        count=4,
        blocks_per_episode=WINDOW,
        congested_share=1.0,
    )
    starts = sorted(episode.start_index for episode in chosen)
    assert all(b - a >= WINDOW for a, b in zip(starts, starts[1:], strict=False))


def test_separate_random_streams_for_orders_and_the_environment(frame):
    """Changing one must not silently shift the other."""
    episode = episodes(frame)[0]
    assert episode.rng().random() != np.random.default_rng(episode.seed).random()


def test_too_short_a_split_fails_loudly(frame):
    tiny = frame.head(10)
    with pytest.raises(ValueError, match="too few"):
        build_episodes(
            tiny, chronological_split(tiny), which="train", count=2, blocks_per_episode=WINDOW
        )


def test_episode_ids_are_unique_and_stable(frame):
    ids = [episode.episode_id for episode in episodes(frame, count=10)]
    assert len(set(ids)) == 10
    assert ids == [episode.episode_id for episode in episodes(frame, count=10)]


def test_blocks_are_a_contiguous_slice_of_d1(frame):
    episode = episodes(frame)[0]
    window = episode.blocks(frame)
    assert window["block_height"].is_monotonic_increasing
    assert isinstance(window, pd.DataFrame)
    assert (window["block_height"].diff().dropna() == 1).all()
