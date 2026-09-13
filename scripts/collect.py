"""Collect dataset D1 — Cardano block congestion history (P1-4).

    python scripts/collect.py --days 90 --out data/processed/
    python scripts/collect.py --days 90 --resume
    python scripts/collect.py --exunits-sample 7

Resumable and rate-limited. Writes a parquet, a ``.sha256`` and a manifest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from batcher.config.params import DEFAULT_SEED
from batcher.data.collector import (
    BLOCKS_PER_DAY,
    collect_blocks,
    collect_exunits,
    merge_exunits,
    staged_block_hashes,
    write_dataset,
)
from batcher.data.sources import BlockfrostSource, KoiosSource

DEFAULT_STAGING = Path("data/raw/d1")

# The chain tip can be reorganised by a short fork. Collecting a few blocks back
# from the tip means a row, once written, does not change under a re-run — which
# is what makes "re-running produces a byte-identical parquet" achievable.
DEFAULT_TIP_LAG = 10


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="days of history to collect")
    # A window defined relative to the chain tip moves every time it is evaluated,
    # so --days alone cannot satisfy "re-running produces a byte-identical parquet"
    # (M1 acceptance, NFR-3). Reproducing a dataset means pinning the heights its
    # manifest recorded; a resumed run must pin them too, or the window slides.
    parser.add_argument("--start-height", type=int, default=None)
    parser.add_argument("--end-height", type=int, default=None)
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--resume", action="store_true", help="continue from the last staged page")
    parser.add_argument(
        "--exunits-sample",
        type=int,
        default=0,
        metavar="DAYS",
        help="also collect per-transaction execution units for DAYS days",
    )
    # Sampling the newest blocks samples whatever regime the chain happens to be in,
    # which for this dataset is its quietest stretch. The proxy question is about
    # blocks near their capacity, so the window must be aimable at congested days.
    parser.add_argument(
        "--exunits-end-height",
        type=int,
        default=None,
        help="end the execution-unit sample here instead of at the newest block",
    )
    parser.add_argument("--source", choices=["koios", "blockfrost"], default="koios")
    parser.add_argument("--blockfrost-project-id", default=None)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--pause", type=float, default=0.25, help="seconds between requests")
    return parser.parse_args(argv)


def build_source(args: argparse.Namespace):
    if args.source == "blockfrost":
        return BlockfrostSource(args.blockfrost_project_id or "", pause_s=args.pause)
    return KoiosSource(pause_s=args.pause)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = build_source(args)

    if args.end_height is not None:
        end_height = args.end_height
        tip = None
    else:
        tip = source.tip_height()
        end_height = tip - DEFAULT_TIP_LAG

    start_height = (
        args.start_height
        if args.start_height is not None
        else end_height - args.days * BLOCKS_PER_DAY + 1
    )
    expected = end_height - start_height + 1

    print(f"source        {source.name}")
    print(f"tip           {tip if tip is not None else 'pinned window, not queried'}")
    print(f"window        {start_height}..{end_height}  ({expected:,} blocks)")
    print(f"staging       {args.staging}")

    collected = 0

    def report(top: int, bottom: int, rows: int) -> None:
        nonlocal collected
        collected += rows
        pct = 100 * collected / expected
        print(f"  page {top} -> {bottom}  (+{rows})  {collected:,}/{expected:,}  {pct:5.1f}%")

    frame = collect_blocks(
        source,
        start_height=start_height,
        end_height=end_height,
        staging_dir=args.staging,
        page_size=args.page_size,
        resume=args.resume,
        on_page=report,
    )

    if frame.empty:
        print("no blocks collected", file=sys.stderr)
        return 1

    if args.exunits_sample:
        if not isinstance(source, KoiosSource):
            print("execution-unit sampling requires the Koios source", file=sys.stderr)
            return 1
        frame = _attach_exunits(source, frame, args)

    paths = write_dataset(frame, args.out, source.name)

    print(f"\nrows          {len(frame):,}")
    print(f"parquet       {paths['parquet']}")
    print(f"checksum      {paths['checksum']}")
    print(f"manifest      {paths['manifest']}")
    print(f"seed          {DEFAULT_SEED}")
    return 0


EXUNITS_STAGING = "exunits.parquet"


def _write_exunits(path: Path, already, fresh):
    """Persist the accumulated execution-unit sample, writing whole or not at all."""
    parts = [part for part in (already, fresh) if part is not None and len(part)]
    combined = pd.concat(parts, ignore_index=True).drop_duplicates(subset="block_height")

    temporary = path.with_suffix(".parquet.tmp")
    combined.to_parquet(temporary, index=False)
    temporary.replace(path)
    return combined


def _attach_exunits(source: KoiosSource, frame, args: argparse.Namespace):
    sample_blocks = args.exunits_sample * BLOCKS_PER_DAY
    if args.exunits_end_height is not None:
        eligible = frame[frame["block_height"] <= args.exunits_end_height]
    else:
        eligible = frame
    window = eligible.tail(sample_blocks)
    print(
        f"\nexecution units for {len(window):,} blocks ending at height "
        f"{int(window['block_height'].max())} (ADR-005 sample)"
    )

    # Execution units accumulate across runs: a second sample aimed at a different
    # window must add to the first, not replace it. Samples are expensive enough
    # that silently discarding one would be a real loss.
    staged_path = args.staging / EXUNITS_STAGING
    already = pd.read_parquet(staged_path) if staged_path.exists() else None
    have = set(already["block_height"]) if already is not None else set()
    if have:
        print(f"  {len(have):,} blocks already sampled in earlier runs")

    todo = window[~window["block_height"].isin(have)]
    hashes = staged_block_hashes(args.staging, todo["block_height"])
    missing = set(todo["block_height"]) - set(hashes)
    if missing:
        print(f"  {len(missing):,} block hashes missing from staging; skipped", file=sys.stderr)
        todo = todo[todo["block_height"].isin(hashes)]

    def report(done: int, total: int) -> None:
        print(f"  exunits {done:,}/{total:,}  {100 * done / total:5.1f}%")

    staged_path.parent.mkdir(parents=True, exist_ok=True)

    def persist(so_far) -> None:
        _write_exunits(staged_path, already, so_far)

    fresh = (
        collect_exunits(source, todo, hashes, on_batch=report, checkpoint=persist)
        if len(todo)
        else None
    )
    exunits = _write_exunits(staged_path, already, fresh)
    print(f"  execution units now cover {len(exunits):,} blocks")

    return merge_exunits(frame, exunits)


if __name__ == "__main__":
    raise SystemExit(main())
