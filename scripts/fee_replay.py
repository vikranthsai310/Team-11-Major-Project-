"""V4 · Validate the fee model against real recorded transactions (X-4, T-F6).

    python scripts/fee_replay.py --count 200

Recomputes the minimum fee for real mainnet transactions from the formula in
``docs/07-CONSTRAINTS-COST-MODEL.md`` §5 and compares it with the fee actually
paid. This validates the fee model against ground truth **independently of the
simulator**, which is why it is worth running before Phase 7 rather than after.

What a match means, precisely: the formula computes the protocol *minimum*. A
transaction may pay more — wallets round up, and the Conway era adds a
reference-script surcharge the pre-Conway formula does not model. So the
invariant under test is ``estimate <= actual``, with exact equality expected for
simple transactions that paid the minimum.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from batcher.build.estimator import fee_lovelace
from batcher.data.sources import KOIOS_BULK_MAX, KoiosSource, sum_redeemer_units
from batcher.eval.manifest import write_manifest


def collect(source: KoiosSource, count: int) -> pd.DataFrame:
    tip = source.tip_height()
    rows: list[dict] = []
    height = tip - 20

    while len(rows) < count:
        blocks = source.blocks_at_or_below(height, KOIOS_BULK_MAX)
        if not blocks:
            break
        hashes = [block.block_hash for block in blocks]
        by_block = source.block_tx_hashes(hashes)
        tx_hashes = [tx for group in by_block.values() for tx in group]

        for start in range(0, len(tx_hashes), KOIOS_BULK_MAX):
            batch = tx_hashes[start : start + KOIOS_BULK_MAX]
            if not batch:
                continue
            for info in source.tx_info(batch):
                mem, steps = sum_redeemer_units(info)
                rows.append(
                    {
                        "tx_hash": info["tx_hash"],
                        "tx_size": int(info["tx_size"]),
                        "mem": mem,
                        "steps": steps,
                        "actual_fee": int(info["fee"]),
                        "has_scripts": bool(info.get("plutus_contracts")),
                    }
                )
        height = min(block.block_height for block in blocks) - 1

    frame = pd.DataFrame(rows[:count])
    frame["estimated_fee"] = [
        fee_lovelace(row.tx_size, row.mem, row.steps) for row in frame.itertuples()
    ]
    frame["residual"] = frame["actual_fee"] - frame["estimated_fee"]
    frame["relative"] = frame["residual"] / frame["actual_fee"]
    return frame


def summarise(frame: pd.DataFrame) -> dict:
    simple = frame[~frame["has_scripts"]]
    scripted = frame[frame["has_scripts"]]

    return {
        "transactions": int(len(frame)),
        "never_overestimates": bool((frame["residual"] >= 0).all()),
        "exact_matches": int((frame["residual"] == 0).sum()),
        "exact_match_rate": float((frame["residual"] == 0).mean()),
        "simple": _group(simple),
        "scripted": _group(scripted),
    }


def _group(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"n": 0}
    return {
        "n": int(len(frame)),
        "exact_matches": int((frame["residual"] == 0).sum()),
        "median_relative_residual": float(frame["relative"].median()),
        "p95_relative_residual": float(np.percentile(frame["relative"], 95)),
        "max_relative_residual": float(frame["relative"].max()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--experiment", default="phase2-fee-replay")
    args = parser.parse_args(argv)

    source = KoiosSource()
    print(f"collecting {args.count} recorded mainnet transactions...")
    frame = collect(source, args.count)
    result = summarise(frame)

    print(f"\ntransactions            {result['transactions']}")
    print(f"formula never exceeds   {result['never_overestimates']}   <- T-F6 invariant")
    print(f"exact minimum-fee match {result['exact_matches']} ({result['exact_match_rate']:.1%})")

    for name in ("simple", "scripted"):
        group = result[name]
        if not group["n"]:
            continue
        print(f"\n{name} transactions (n={group['n']})")
        print(f"  exact matches          {group['exact_matches']}")
        print(f"  median under-estimate  {group['median_relative_residual']:+.2%}")
        print(f"  95th percentile        {group['p95_relative_residual']:+.2%}")
        print(f"  worst                  {group['max_relative_residual']:+.2%}")

    manifest = write_manifest(
        args.experiment, seed=0, source="koios", result=result, count=args.count
    )
    frame.to_parquet(manifest.parent / "fee_replay.parquet", index=False)
    (manifest.parent / "fee_replay.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"\nmanifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
