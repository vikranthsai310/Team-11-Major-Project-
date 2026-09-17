"""P7-8 · Run the batcher against preprod. **Shadow mode unless ``--live``.**

    python scripts/run_batcher.py --policy p2
    python scripts/run_batcher.py --policy p2 --live --log-json | tee logs/batcher.jsonl

Shadow mode reads preprod, decides every block, and builds and signs the batch it
would send — then logs it and submits nothing. ``--live`` submits.

Ctrl+C asks for a clean stop: the batcher finishes waiting for any batch in flight
(settled at ``--confirmation-depth``, expired, invalidated or rolled back) and starts
no new one. A second Ctrl+C exits immediately and warns if that leaves a batch
holding the pool (runbook §7.2).

Blockfrost is wrapped in ``ResilientChain`` (retries with backoff, a circuit
breaker) unless ``--no-resilience``: an outage is logged as ``api_unavailable``
and polled through, never decided or submitted on.

Gate A is calibrated unless ``--no-calibration``: limits are held to the stricter
of the live protocol parameters and the configured constants, and estimates are
corrected by measured transactions, seeded from the D4 file (``--calibration-seed``)
when it exists. An oversize build is retried at half the batch size.

Prerequisites: ``onchain/deployment.preprod.json`` from ``deploy_dex.py --submit``,
``batcher.skey`` in ``BATCHER_KEY_DIR``, ``BLOCKFROST_PROJECT_ID`` for a preprod
project in ``.env``, and the Aiken compiler to re-derive the deployed scripts.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from pycardano import Network, PaymentSigningKey

from batcher.build.calibration import REFRESH_BLOCKS, CapacityCalibrator, read_d4_rows
from batcher.config.params import D_MAX
from batcher.config.settings import load_settings
from batcher.live.resilience import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RETRIES,
    ResilientChain,
)
from batcher.onchain import deployment as dex
from batcher.policy.optimizer import ConstrainedOptimizer
from batcher.policy.static import Greedy

D4_DEFAULT = Path("data/live/d4_preprod.jsonl")


def human(record: dict) -> str:
    base = f"block {record['block_height']} slot {record['abs_slot']}"
    if record["pool_locked"]:
        return f"{base}  LOCKED  {record['resolution']}  {record['tx_id']}"
    detail = f"queue {record['queue_depth']} oldest {record['oldest_wait']}"
    if record["action"] == "SUBMIT":
        detail += (
            f"  SUBMIT n={record['n']} executed={record['executed']} fee={record['fee_lovelace']}"
        )
    else:
        detail += "  WAIT"
    if record.get("build_attempts"):
        detail += f"  shrunk {record['build_attempts']}"
    capacity = record.get("capacity") or {}
    for warning in capacity.get("warnings", []):
        detail += f"  WARNING {warning}"
    return f"{base}  {detail}  [{record['resolution']}]"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=["p2", "e3"], default="p2")
    parser.add_argument(
        "--n-min", type=int, default=4, help="P2; 4 is the test-split trade-off point"
    )
    parser.add_argument("--d-max", type=int, default=D_MAX)
    parser.add_argument("--live", action="store_true", help="submit batches to preprod")
    parser.add_argument("--log-json", action="store_true")
    parser.add_argument("--max-blocks", type=int, default=None)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--d4", type=Path, default=D4_DEFAULT)
    parser.add_argument("--key-dir", type=Path, default=None)
    parser.add_argument(
        "--confirmation-depth",
        type=int,
        default=None,
        help="blocks a batch must be buried under before it is settled (default 3)",
    )
    parser.add_argument("--api-retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument(
        "--breaker-failures",
        type=int,
        default=DEFAULT_FAILURE_THRESHOLD,
        help="consecutive API failures that open the circuit breaker",
    )
    parser.add_argument("--breaker-cooldown", type=float, default=DEFAULT_COOLDOWN_SECONDS)
    parser.add_argument(
        "--no-resilience",
        action="store_true",
        help="call Blockfrost directly: no retries, breaker or outage handling",
    )
    parser.add_argument(
        "--no-calibration",
        action="store_true",
        help="use the static Gate A: configured limits, uncorrected estimates, no retry",
    )
    parser.add_argument(
        "--calibration-seed",
        type=Path,
        default=D4_DEFAULT,
        help="D4 rows to seed the estimate corrections from (default: the D4 file)",
    )
    parser.add_argument(
        "--no-calibration-seed", action="store_true", help="start the corrections at 1.0"
    )
    parser.add_argument(
        "--protocol-refresh-blocks",
        type=int,
        default=REFRESH_BLOCKS,
        help="blocks between protocol parameter reads (a new epoch also triggers one)",
    )
    args = parser.parse_args(argv)

    settings = load_settings()  # refuses anything but preprod
    if not settings.blockfrost_project_id:
        print("BLOCKFROST_PROJECT_ID is not set in .env (a preprod project is required).")
        return 1
    if not dex.RECORD.exists():
        print("No deployment record; run scripts/deploy_dex.py --submit first.")
        return 1
    skey_path = (args.key_dir or settings.batcher_key_dir) / "batcher.skey"
    if not skey_path.exists():
        print(f"No {skey_path}. Run: python scripts/generate_keys.py --name batcher")
        return 1

    from blockfrost import ApiUrls
    from pycardano import BlockFrostChainContext

    from batcher.live.chain import BlockfrostChain
    from batcher.live.daemon import CONFIRMATION_DEPTH, LiveBatcher

    deployment = dex.load()
    scripts = dex.scripts_for(deployment)  # refuses scripts that no longer match the deployment
    context = BlockFrostChainContext(settings.blockfrost_project_id, base_url=ApiUrls.preprod.value)
    if context.network != Network.TESTNET:
        raise SystemExit("the chain context is not a testnet; refusing to run")

    policy = (
        ConstrainedOptimizer(d_max=args.d_max, n_min=args.n_min)
        if args.policy == "p2"
        else Greedy()
    )
    emit = (
        (lambda r: print(json.dumps(r), flush=True))
        if args.log_json
        else (lambda r: print(human(r), flush=True))
    )
    chain = BlockfrostChain(context)
    if not args.no_resilience:
        chain = ResilientChain(
            chain,
            retries=args.api_retries,
            failure_threshold=args.breaker_failures,
            cooldown_seconds=args.breaker_cooldown,
        )
    calibrator = None
    if not args.no_calibration:
        calibrator = CapacityCalibrator(refresh_blocks=args.protocol_refresh_blocks)
        if not args.no_calibration_seed:
            seeded = calibrator.seed_from_d4(read_d4_rows(args.calibration_seed))
            factors = {d: round(f, 3) for d, f in calibrator.factors.items()}
            print(f"calibration seeded from {seeded} D4 rows; factors {factors}", file=sys.stderr)
    batcher = LiveBatcher(
        chain,
        policy,
        deployment,
        scripts,
        PaymentSigningKey.load(str(skey_path)),
        submit=args.live,
        d_max=args.d_max,
        confirmation_depth=(
            CONFIRMATION_DEPTH if args.confirmation_depth is None else args.confirmation_depth
        ),
        emit=emit,
        d4_path=args.d4 if args.live else None,
        calibration=not args.no_calibration,
        calibrator=calibrator,
    )

    def on_interrupt(_signum, _frame):
        if batcher.stop_requested:
            if batcher.pool_locked:
                print(
                    "Exiting with a batch in flight: its orders stay committed until TTL.",
                    file=sys.stderr,
                )
            raise KeyboardInterrupt
        batcher.request_stop()
        print("Stopping once no batch is in flight (Ctrl+C again to force).", file=sys.stderr)

    signal.signal(signal.SIGINT, on_interrupt)
    mode = "LIVE — submitting to preprod" if args.live else "SHADOW — nothing is submitted"
    print(f"{policy.name} · {mode}", file=sys.stderr)
    blocks = batcher.run(max_blocks=args.max_blocks, poll_seconds=args.poll_seconds)
    print(f"stopped cleanly after {blocks} blocks; pool unlocked", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
