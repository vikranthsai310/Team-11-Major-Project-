"""M1 · Chain data collector — produces dataset D1.

Paging is by **height range**, not by offset: each page asks for the blocks at
or below a height the previous page established. Offset paging over a chain that
grows while you read it returns different rows on every run, which would break
both resumability and the byte-identical re-run requirement.

Completed pages are staged as whole parquet parts and never partially written,
so an interrupted collection resumes from the lowest height already persisted
(T-N2).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from batcher.config import protocol
from batcher.config.protocol import (
    MAX_BLOCK_EX_MEM,
    MAX_BLOCK_EX_STEPS,
    MAX_BLOCK_SIZE,
    SLOT_SECONDS,
)
from batcher.data.sources import KOIOS_BULK_MAX, BlockRecord, BlockSource, KoiosSource
from batcher.eval.manifest import git_state, module_values

BLOCKS_PER_DAY = 24 * 60 * 60 // (SLOT_SECONDS * 20)  # ~4,300 at mean 20 s cadence

D1_COLUMNS = [
    "block_height",
    "abs_slot",
    "block_time",
    "block_size",
    "fill_pct",
    "tx_count",
    "mem_exunits",
    "step_exunits",
    "mem_pct",
    "step_pct",
    "slot_gap",
    "exunits_source",
]

EXUNITS_SOURCES = ["dbsync", "per_tx", "absent"]

D1_DTYPES = {
    "block_height": "int64",
    "abs_slot": "int64",
    "block_time": "datetime64[ns, UTC]",
    "block_size": "int32",
    "fill_pct": "float32",
    "tx_count": "int16",
    "mem_exunits": "Int64",
    "step_exunits": "Int64",
    "mem_pct": "float32",
    "step_pct": "float32",
    "slot_gap": "int32",
    "exunits_source": pd.CategoricalDtype(EXUNITS_SOURCES),
}

_PART_PATTERN = re.compile(r"part-(\d+)-(\d+)\.parquet$")


def records_to_frame(records: Iterable[BlockRecord]) -> pd.DataFrame:
    """Normalised source records -> raw staging rows (no ``slot_gap`` yet).

    ``block_hash`` is kept in staging because the execution-unit sampler needs it
    to walk a block's transactions; ``finalise`` drops it, since D1 itself is
    aggregate statistics only.
    """
    return pd.DataFrame([asdict(record) for record in records])


def finalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Sort ascending, derive the computed columns and apply the D1 dtypes.

    ``slot_gap`` can only be computed once the full window is ordered, so it is
    derived here rather than per page.
    """
    frame = frame.drop_duplicates(subset="block_height").sort_values("block_height")
    frame = frame.reset_index(drop=True)

    if frame.empty:
        return pd.DataFrame({column: pd.Series(dtype=dtype) for column, dtype in D1_DTYPES.items()})

    frame["fill_pct"] = frame["block_size"] / MAX_BLOCK_SIZE
    frame["slot_gap"] = frame["abs_slot"].diff().fillna(0)

    for column in ("mem_exunits", "step_exunits"):
        if column not in frame:
            frame[column] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
        frame[column] = frame[column].astype("Int64")
    if "exunits_source" not in frame:
        frame["exunits_source"] = "absent"

    # Nullable Int64 divided into a float leaves pd.NA in place, which float32
    # cannot hold; to_numpy converts the missing values to NaN on the way out.
    frame["mem_pct"] = _ratio(frame["mem_exunits"], MAX_BLOCK_EX_MEM)
    frame["step_pct"] = _ratio(frame["step_exunits"], MAX_BLOCK_EX_STEPS)

    frame["block_time"] = pd.to_datetime(frame["block_time"], unit="s", utc=True)

    return frame[D1_COLUMNS].astype(D1_DTYPES)


def _ratio(numerator: pd.Series, denominator: int) -> np.ndarray:
    return (numerator.astype("Float64") / denominator).to_numpy(dtype="float32", na_value=np.nan)


def staged_parts(staging_dir: Path) -> list[Path]:
    return sorted(
        (path for path in staging_dir.glob("part-*.parquet") if _PART_PATTERN.search(path.name)),
        key=lambda path: int(_PART_PATTERN.search(path.name).group(2)),
    )


def staged_block_hashes(staging_dir: Path, heights: Iterable[int]) -> dict[int, str]:
    """``{block_height: block_hash}`` recovered from staging, for the ExUnit sampler."""
    wanted = set(heights)
    found: dict[int, str] = {}
    for path in staged_parts(staging_dir):
        part = pd.read_parquet(path, columns=["block_height", "block_hash"])
        for height, block_hash in zip(part["block_height"], part["block_hash"], strict=True):
            if int(height) in wanted:
                found[int(height)] = str(block_hash)
    return found


def lowest_staged_height(staging_dir: Path) -> int | None:
    parts = staged_parts(staging_dir)
    if not parts:
        return None
    return min(int(_PART_PATTERN.search(path.name).group(2)) for path in parts)


def collect_blocks(
    source: BlockSource,
    *,
    start_height: int,
    end_height: int,
    staging_dir: Path,
    page_size: int = 1000,
    resume: bool = True,
    on_page: Callable[[int, int, int], None] | None = None,
) -> pd.DataFrame:
    """Collect ``[start_height, end_height]`` into ``staging_dir``, then return it.

    Each page is written whole or not at all. Re-invoking with ``resume=True``
    continues below the lowest height already staged.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)

    cursor = end_height
    if resume:
        staged = lowest_staged_height(staging_dir)
        if staged is not None:
            cursor = min(cursor, staged - 1)
    else:
        for path in staged_parts(staging_dir):
            path.unlink()

    while cursor >= start_height:
        records = [
            record
            for record in source.blocks_at_or_below(cursor, page_size)
            if record.block_height >= start_height
        ]
        if not records:
            break

        page = records_to_frame(records)
        top = int(page["block_height"].max())
        bottom = int(page["block_height"].min())

        # Write to a temporary name and rename, so an interrupted write can
        # never leave a partial page that resume would mistake for a whole one.
        target = staging_dir / f"part-{top}-{bottom}.parquet"
        temporary = target.with_suffix(".parquet.tmp")
        page.to_parquet(temporary, index=False)
        temporary.replace(target)

        if on_page is not None:
            on_page(top, bottom, len(page))

        cursor = bottom - 1

    parts = staged_parts(staging_dir)
    if not parts:
        return finalise(pd.DataFrame(columns=["block_height"]))

    combined = pd.concat([pd.read_parquet(path) for path in parts], ignore_index=True)
    combined = combined[combined["block_height"].between(start_height, end_height)]
    return finalise(combined)


def merge_exunits(frame: pd.DataFrame, exunits: pd.DataFrame) -> pd.DataFrame:
    """Attach per-block execution units to the sampled window (ADR-005).

    Rows outside the sample keep null units and ``exunits_source == "absent"``.
    Writing ``0`` there would make unsampled blocks look empty and corrupt every
    downstream congestion statistic — the ADR-005 regression guard in T-N1.
    """
    merged = frame.drop(columns=["mem_exunits", "step_exunits", "mem_pct", "step_pct"]).merge(
        exunits[["block_height", "mem_exunits", "step_exunits"]],
        on="block_height",
        how="left",
    )
    sampled = merged["mem_exunits"].notna()
    merged["exunits_source"] = merged["exunits_source"].astype(str)
    merged.loc[sampled, "exunits_source"] = "per_tx"
    return finalise(merged)


def collect_exunits(
    source: KoiosSource,
    blocks: pd.DataFrame,
    block_hashes: dict[int, str],
    *,
    block_batch: int = KOIOS_BULK_MAX,
    tx_batch: int = KOIOS_BULK_MAX,
    on_batch: Callable[[int, int], None] | None = None,
    checkpoint: Callable[[pd.DataFrame], None] | None = None,
) -> pd.DataFrame:
    """Per-block execution units, summed over every redeemer in every transaction.

    Expensive by construction: neither Koios nor Blockfrost exposes execution
    units on the block endpoint, so this walks transactions. That cost is the
    entire reason D1 samples execution units rather than collecting them across
    the full window (ADR-005).

    ``checkpoint`` is called with everything collected so far after each block
    batch. Because a sample costs tens of minutes, losing it to a transient
    network failure at 57 % is not an acceptable outcome — and was the observed
    one before this existed.
    """
    heights = sorted(blocks["block_height"].tolist())
    rows = []

    for index in range(0, len(heights), block_batch):
        chunk = heights[index : index + block_batch]
        hashes = [block_hashes[height] for height in chunk]
        tx_by_block = source.block_tx_hashes(hashes)

        units: dict[str, tuple[int, int]] = {}
        all_tx = [tx for hashes_ in tx_by_block.values() for tx in hashes_]
        for offset in range(0, len(all_tx), tx_batch):
            units |= source.tx_execution_units(all_tx[offset : offset + tx_batch])

        for height, block_hash in zip(chunk, hashes, strict=True):
            mem = steps = 0
            for tx_hash in tx_by_block.get(block_hash, []):
                tx_mem, tx_steps = units.get(tx_hash, (0, 0))
                mem += tx_mem
                steps += tx_steps
            rows.append({"block_height": height, "mem_exunits": mem, "step_exunits": steps})

        if on_batch is not None:
            on_batch(index + len(chunk), len(heights))
        if checkpoint is not None:
            checkpoint(_exunits_frame(rows))

    return _exunits_frame(rows)


def _exunits_frame(rows: list[dict[str, int]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["block_height", "mem_exunits", "step_exunits"])


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_name(frame: pd.DataFrame) -> str:
    start = frame["block_time"].min().strftime("%Y%m%d")
    end = frame["block_time"].max().strftime("%Y%m%d")
    return f"d1_blocks_{start}_{end}"


def write_dataset(frame: pd.DataFrame, out_dir: Path, source_name: str) -> dict[str, Path]:
    """Write the parquet, its ``.sha256`` and the dataset manifest (P1-3, P1-8).

    The parquet is gitignored; the checksum and the manifest are committed, so an
    experiment referencing a dataset that has since changed fails loudly.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    name = dataset_name(frame)

    parquet_path = out_dir / f"{name}.parquet"
    frame.to_parquet(parquet_path, index=False)

    checksum = sha256_of(parquet_path)
    checksum_path = out_dir / f"{name}.sha256"
    checksum_path.write_text(f"{checksum}  {parquet_path.name}\n")

    sampled = frame["exunits_source"] == "per_tx"
    manifest = {
        "dataset": name,
        "source": source_name,
        "rows": int(len(frame)),
        "checksum_sha256": checksum,
        "window": {
            "start_height": int(frame["block_height"].min()),
            "end_height": int(frame["block_height"].max()),
            "start_time": frame["block_time"].min().isoformat(),
            "end_time": frame["block_time"].max().isoformat(),
        },
        "exunits_coverage": {
            "per_tx": int(sampled.sum()),
            "absent": int((~sampled).sum()),
        },
        "collector_git": git_state(),
        "protocol": module_values(protocol),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {"parquet": parquet_path, "checksum": checksum_path, "manifest": manifest_path}
