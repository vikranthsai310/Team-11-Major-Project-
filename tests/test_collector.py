"""T-N1 and T-N2 — collector to D1, and resumability."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from batcher.config.protocol import MAX_BLOCK_EX_MEM, MAX_BLOCK_SIZE
from batcher.data.collector import (
    D1_COLUMNS,
    collect_blocks,
    collect_exunits,
    finalise,
    lowest_staged_height,
    merge_exunits,
    records_to_frame,
    sha256_of,
    staged_block_hashes,
    write_dataset,
)
from conftest import BASE_HEIGHT, FakeSource, make_records


@pytest.fixture
def collected(source, tmp_path):
    return collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=tmp_path / "staging",
        page_size=50,
    )


def test_d1_has_the_specified_schema_and_dtypes(collected):
    """T-N1 — the exact schema from docs/05-DATA-SPEC.md §D1."""
    assert list(collected.columns) == D1_COLUMNS
    assert collected["block_height"].dtype == "int64"
    assert collected["abs_slot"].dtype == "int64"
    assert collected["block_size"].dtype == "int32"
    assert collected["fill_pct"].dtype == "float32"
    assert collected["tx_count"].dtype == "int16"
    assert collected["mem_exunits"].dtype == "Int64"
    assert collected["slot_gap"].dtype == "int32"
    assert str(collected["block_time"].dtype).startswith("datetime64[ns, UTC")


def test_rows_are_ordered_and_derived_columns_are_correct(collected):
    assert collected["block_height"].is_monotonic_increasing
    assert collected["abs_slot"].is_monotonic_increasing

    expected_fill = collected["block_size"] / MAX_BLOCK_SIZE
    assert np.allclose(collected["fill_pct"], expected_fill, atol=1e-7)

    expected_gap = collected["abs_slot"].diff().fillna(0)
    assert np.array_equal(collected["slot_gap"], expected_gap)


def test_unsampled_execution_units_are_null_never_zero(collected):
    """ADR-005 regression guard. Zero would make unsampled blocks look empty."""
    assert (collected["exunits_source"] == "absent").all()
    assert collected["mem_exunits"].isna().all()
    assert collected["step_exunits"].isna().all()
    assert not (collected["mem_exunits"].fillna(-1) == 0).any()


def test_interrupted_collection_resumes_to_the_same_file(source, tmp_path):
    """T-N2 — interrupting and resuming yields the same result as one clean run."""
    staging = tmp_path / "partial"
    tip = source.tip_height()

    # A first pass that stops early, as an interrupted run would.
    partial = FakeSource(list(source.by_height.values()))
    collect_blocks(
        partial,
        start_height=tip - 99,
        end_height=tip,
        staging_dir=staging,
        page_size=50,
    )
    assert lowest_staged_height(staging) == tip - 99

    resumed = collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=tip,
        staging_dir=staging,
        page_size=50,
        resume=True,
    )

    uninterrupted = collect_blocks(
        FakeSource(list(source.by_height.values())),
        start_height=BASE_HEIGHT,
        end_height=tip,
        staging_dir=tmp_path / "clean",
        page_size=50,
    )

    pd.testing.assert_frame_equal(resumed, uninterrupted)


def test_resume_does_not_refetch_what_is_already_staged(source, tmp_path):
    staging = tmp_path / "staging"
    tip = source.tip_height()
    collect_blocks(source, start_height=tip - 99, end_height=tip, staging_dir=staging, page_size=50)
    after_first = source.pages_served

    collect_blocks(
        source,
        start_height=tip - 99,
        end_height=tip,
        staging_dir=staging,
        page_size=50,
        resume=True,
    )
    assert source.pages_served == after_first


def test_rerunning_produces_a_byte_identical_parquet(source, tmp_path):
    """M1 acceptance: re-running the collector produces a byte-identical parquet."""
    tip = source.tip_height()
    frames = []
    for run in ("a", "b"):
        frame = collect_blocks(
            FakeSource(list(source.by_height.values())),
            start_height=BASE_HEIGHT,
            end_height=tip,
            staging_dir=tmp_path / f"staging_{run}",
            page_size=50,
        )
        write_dataset(frame, tmp_path / run, "fake")
        frames.append(frame)

    pd.testing.assert_frame_equal(*frames)
    name = sorted((tmp_path / "a").glob("*.parquet"))[0].name
    assert sha256_of(tmp_path / "a" / name) == sha256_of(tmp_path / "b" / name)


def test_partial_pages_are_never_left_behind(source, tmp_path):
    staging = tmp_path / "staging"
    collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=staging,
        page_size=50,
    )
    assert list(staging.glob("*.tmp")) == []


def test_collection_gap_survives_to_the_verifier(tmp_path):
    """A hole in block_height must reach D1 as a hole, not be silently closed."""
    missing = BASE_HEIGHT + 40
    source = FakeSource(make_records(100, skip={missing}))
    frame = collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=tmp_path / "staging",
        page_size=25,
    )
    assert missing not in set(frame["block_height"])
    assert (frame["block_height"].diff().dropna() != 1).any()


def test_exunits_merge_marks_only_the_sampled_window(collected):
    sample = collected.tail(20)["block_height"]
    exunits = pd.DataFrame(
        {
            "block_height": sample,
            "mem_exunits": [1_000_000] * len(sample),
            "step_exunits": [200_000_000] * len(sample),
        }
    )

    merged = merge_exunits(collected, exunits)
    sampled = merged["exunits_source"] == "per_tx"

    assert sampled.sum() == len(sample)
    assert merged.loc[sampled, "mem_exunits"].eq(1_000_000).all()
    assert merged.loc[~sampled, "mem_exunits"].isna().all()
    assert merged.loc[sampled, "mem_pct"].round(6).eq(round(1_000_000 / MAX_BLOCK_EX_MEM, 6)).all()
    assert list(merged.columns) == D1_COLUMNS


def test_block_hashes_are_recoverable_from_staging_for_the_exunit_sampler(source, tmp_path):
    staging = tmp_path / "staging"
    frame = collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=staging,
        page_size=50,
    )
    heights = frame["block_height"].tail(5).tolist()
    hashes = staged_block_hashes(staging, heights)
    assert set(hashes) == set(heights)
    assert all(len(h) == 64 for h in hashes.values())


def test_write_dataset_emits_parquet_checksum_and_manifest(collected, tmp_path):
    paths = write_dataset(collected, tmp_path / "processed", "koios")

    assert paths["parquet"].exists()
    assert sha256_of(paths["parquet"]) == paths["checksum"].read_text().split()[0]

    manifest = json.loads(paths["manifest"].read_text())
    assert manifest["rows"] == len(collected)
    assert manifest["source"] == "koios"
    assert manifest["protocol"]["MAX_BLOCK_SIZE"] == MAX_BLOCK_SIZE
    assert manifest["exunits_coverage"]["absent"] == len(collected)


class FakeKoios:
    """Serves two Plutus transactions per block, with known execution units."""

    def __init__(self, per_tx=(500_000, 200_000_000), tx_per_block=2):
        self.per_tx = per_tx
        self.tx_per_block = tx_per_block
        self.tx_info_calls = 0

    def block_tx_hashes(self, block_hashes):
        return {
            block_hash: [f"{block_hash}-tx{i}" for i in range(self.tx_per_block)]
            for block_hash in block_hashes
        }

    def tx_execution_units(self, tx_hashes):
        self.tx_info_calls += 1
        return {tx_hash: self.per_tx for tx_hash in tx_hashes}


def test_exunits_sampler_sums_every_transaction_in_a_block(collected):
    window = collected.tail(6)
    hashes = {int(height): f"{height:064x}" for height in window["block_height"]}
    source = FakeKoios()

    exunits = collect_exunits(source, window, hashes, block_batch=3, tx_batch=4)

    assert len(exunits) == 6
    assert (exunits["mem_exunits"] == 2 * 500_000).all()
    assert (exunits["step_exunits"] == 2 * 200_000_000).all()
    assert set(exunits["block_height"]) == set(window["block_height"])


def test_exunits_sampler_batches_transaction_lookups(collected):
    """Per-transaction fetching is the expensive part; it must not be one call per tx."""
    window = collected.tail(10)
    hashes = {int(height): f"{height:064x}" for height in window["block_height"]}
    source = FakeKoios()

    collect_exunits(source, window, hashes, block_batch=5, tx_batch=10)

    # 10 blocks x 2 tx = 20 transactions; at 10 per call that is 2 calls, not 20.
    assert source.tx_info_calls == 2


def test_exunits_sampler_checkpoints_progress(collected):
    """A sample costs tens of minutes; a failure at 57 % must not lose all of it."""
    window = collected.tail(20)
    hashes = {int(height): f"{height:064x}" for height in window["block_height"]}

    checkpoints = []
    collect_exunits(
        FakeKoios(), window, hashes, block_batch=5, checkpoint=lambda f: checkpoints.append(len(f))
    )

    assert checkpoints == [5, 10, 15, 20]


def test_progress_survives_a_failure_part_way_through(collected):
    window = collected.tail(20)
    hashes = {int(height): f"{height:064x}" for height in window["block_height"]}

    class FailsHalfway(FakeKoios):
        def tx_execution_units(self, tx_hashes):
            if self.tx_info_calls >= 2:
                raise ConnectionResetError("connection reset by peer")
            return super().tx_execution_units(tx_hashes)

    saved: list[int] = []
    with pytest.raises(ConnectionResetError):
        collect_exunits(
            FailsHalfway(),
            window,
            hashes,
            block_batch=5,
            checkpoint=lambda f: saved.append(len(f)),
        )

    assert saved, "work completed before the failure was not checkpointed"
    assert saved[-1] == 10


def test_a_block_with_no_plutus_transactions_records_zero_not_null(collected):
    """Zero is correct *inside* the sample: the block ran no scripts. Only
    unsampled blocks carry null (ADR-005)."""
    window = collected.tail(3)
    hashes = {int(height): f"{height:064x}" for height in window["block_height"]}

    exunits = collect_exunits(FakeKoios(tx_per_block=0), window, hashes)
    assert (exunits["mem_exunits"] == 0).all()

    merged = merge_exunits(collected, exunits)
    sampled = merged["exunits_source"] == "per_tx"
    assert merged.loc[sampled, "mem_exunits"].eq(0).all()
    assert merged.loc[~sampled, "mem_exunits"].isna().all()


def test_finalise_drops_duplicate_heights():
    records = make_records(10)
    frame = records_to_frame(records + records[:3])
    assert len(finalise(frame)) == 10
