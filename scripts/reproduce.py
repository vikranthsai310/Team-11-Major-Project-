"""P6-17 · Reproduce a published result from its manifest.

    python scripts/reproduce.py --manifest experiments/<id>/manifest.json --check

A reader should be able to regenerate every figure from the repository, a seed
and a dataset checksum, bit-identically (NFR-3). This checks the preconditions a
reproduction depends on, in the order that catches the most common failure first:

1. the dataset on disk has the checksum the manifest recorded
2. the working tree is at the recorded git SHA, or the difference is reported
3. the protocol parameters and tunables in force match the manifest's config hash

With ``--check`` it stops there. Without it, it prints the command that
regenerates the experiment. It never checks out a different commit on its own:
silently moving someone's working tree to reproduce a number is not a thing a
script should decide to do.

A mismatch is a defect to file, not to work around.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from batcher.data.collector import sha256_of
from batcher.eval.manifest import config_hash

DATASET_DIR = Path("data/processed")


def head_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def find_dataset(checksum: str) -> Path | None:
    for path in sorted(DATASET_DIR.glob("*.parquet")):
        if sha256_of(path) == checksum:
            return path
    return None


def check(manifest: dict) -> list[tuple[str, bool, str]]:
    findings = []

    recorded = manifest.get("dataset_checksum")
    if recorded:
        dataset = find_dataset(recorded)
        findings.append(
            (
                "dataset checksum",
                dataset is not None,
                str(dataset)
                if dataset
                else f"no parquet in {DATASET_DIR} has sha256 {recorded[:12]}",
            )
        )
    else:
        findings.append(("dataset checksum", True, "not applicable — experiment reads no dataset"))

    recorded_sha = (manifest.get("git") or {}).get("sha")
    current = head_sha()
    findings.append(
        (
            "git revision",
            recorded_sha is None or recorded_sha == current,
            f"recorded {str(recorded_sha)[:10]}, current {str(current)[:10]}",
        )
    )
    if (manifest.get("git") or {}).get("dirty"):
        findings.append(
            ("clean tree at record time", False, "the manifest was written from a dirty tree")
        )

    recorded_hash = manifest.get("config_hash")
    findings.append(
        (
            "config hash",
            recorded_hash == config_hash(),
            f"recorded {str(recorded_hash)[:12]}, current {config_hash()[:12]}",
        )
    )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="verify preconditions only")
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text())
    print(f"experiment  {manifest.get('experiment_id')}")
    print(f"seed        {manifest.get('seed')}")
    print(f"created     {manifest.get('created_utc')}\n")

    findings = check(manifest)
    for name, ok, detail in findings:
        print(f"  {'ok ' if ok else 'FAIL'}  {name:<26} {detail}")

    failed = [name for name, ok, _ in findings if not ok]
    if failed:
        print(
            f"\n{len(failed)} precondition(s) failed. File it as a defect; do not work around it."
        )
        if "git revision" in failed:
            sha = (manifest.get("git") or {}).get("sha")
            print(f"To reproduce exactly, check out {sha} yourself and re-run this check.")
        return 1

    print("\nAll preconditions hold — a re-run should reproduce the recorded numbers.")
    if not args.check:
        seed = manifest.get("seed")
        print(f"Re-run the experiment named in {args.manifest.parent} with seed {seed}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
