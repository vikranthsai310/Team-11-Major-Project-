"""Verify a D1 parquet before anything is built on it (P1-7).

    python scripts/verify_dataset.py data/processed/d1_blocks_*.parquet

Checks height continuity, monotone slots, the execution-unit null policy and the
recorded checksum. A dataset whose provenance is uncertain contaminates every
result derived from it, so this exits non-zero rather than warning.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from batcher.config.protocol import MAX_BLOCK_SIZE
from batcher.data.collector import D1_COLUMNS, sha256_of


def check(frame: pd.DataFrame, path: Path) -> list[str]:
    failures: list[str] = []

    missing = [column for column in D1_COLUMNS if column not in frame.columns]
    if missing:
        failures.append(f"missing columns: {missing}")
        return failures

    heights = frame["block_height"]
    if not heights.is_monotonic_increasing or not heights.is_unique:
        failures.append("block_height is not strictly increasing")

    gaps = heights.diff().dropna()
    holes = gaps[gaps != 1]
    if len(holes) > 0:
        failures.append(
            f"{len(holes)} gap(s) in block_height; largest {int(holes.max())} at "
            f"height {int(heights[holes.idxmax()])}"
        )

    if not frame["abs_slot"].is_monotonic_increasing or not frame["abs_slot"].is_unique:
        failures.append("abs_slot is not strictly increasing")

    oversized = frame[frame["block_size"] > MAX_BLOCK_SIZE]
    if len(oversized) > 0:
        failures.append(
            f"{len(oversized)} block(s) exceed MAX_BLOCK_SIZE — Byron epoch-boundary "
            "blocks must be excluded, not clipped"
        )

    if not frame["fill_pct"].between(0, 1).all():
        failures.append("fill_pct outside [0, 1]")

    # ADR-005 guard: an unsampled block has *null* execution units, never zero.
    absent = frame["exunits_source"] == "absent"
    if frame.loc[absent, "mem_exunits"].notna().any():
        failures.append("rows marked 'absent' carry execution units")
    if frame.loc[~absent, "mem_exunits"].isna().any():
        failures.append("rows marked sampled are missing execution units")

    checksum_path = path.with_suffix(".sha256")
    if checksum_path.exists():
        recorded = checksum_path.read_text().split()[0]
        actual = sha256_of(path)
        if recorded != actual:
            failures.append(f"checksum mismatch: recorded {recorded[:16]}, actual {actual[:16]}")
    else:
        failures.append(f"no checksum file at {checksum_path}")

    manifest_path = path.parent / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("rows") != len(frame):
            failures.append(f"manifest row count {manifest.get('rows')} != actual {len(frame)}")

    return failures


def summarise(frame: pd.DataFrame) -> None:
    sampled = int((frame["exunits_source"] == "per_tx").sum())
    print(f"rows              {len(frame):,}")
    print(f"heights           {frame['block_height'].min()} .. {frame['block_height'].max()}")
    print(f"slots             {frame['abs_slot'].min()} .. {frame['abs_slot'].max()}")
    print(f"time              {frame['block_time'].min()} .. {frame['block_time'].max()}")
    print(f"fill_pct mean     {frame['fill_pct'].mean():.4f}")
    print(f"fill_pct  > 80 %  {100 * (frame['fill_pct'] > 0.80).mean():.2f}%")
    print(f"fill_pct  > 90 %  {100 * (frame['fill_pct'] > 0.90).mean():.2f}%")
    print(f"slot_gap mean     {frame['slot_gap'][1:].mean():.2f} slots")
    print(f"exunits sampled   {sampled:,} of {len(frame):,}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args(argv)

    exit_code = 0
    for path in args.paths:
        print(f"\n=== {path} ===")
        frame = pd.read_parquet(path)
        summarise(frame)

        failures = check(frame, path)
        if failures:
            exit_code = 1
            print("\nFAILED")
            for failure in failures:
                print(f"  - {failure}", file=sys.stderr)
        else:
            print("\nOK — all checks passed")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
