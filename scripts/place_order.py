"""P7-11 · Place a demo order from the ``user`` key. **Dry run unless ``--submit``.**

    python scripts/place_order.py --amount-ada 10 --min-out 9000
    python scripts/place_order.py --amount-ada 10 --min-out 9000 --submit

Plays the part of a swap user's wallet: locks ``--amount-ada`` plus a deposit at the
order script with an ``OrderDatum`` (AtoB: sell ADA for the pool token). The
batcher never talks to the user; it finds this UTxO on chain.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pycardano import Network, PaymentSigningKey

from batcher.build.submitter import A_TO_B
from batcher.config.settings import load_settings
from batcher.onchain import deployment as dex

LOVELACE_PER_ADA = 1_000_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-dir", type=Path, default=None)
    parser.add_argument("--amount-ada", type=float, default=10.0)
    parser.add_argument("--min-out", type=int, required=True)
    parser.add_argument("--margin-ada", type=float, default=1.0)
    parser.add_argument(
        "--deposit-ada", type=float, default=5.0, help="covers payout min-ADA and charges"
    )
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv)

    settings = load_settings()
    key_dir = args.key_dir or settings.batcher_key_dir
    skey_path = key_dir / "user.skey"
    if not skey_path.exists():
        print(f"No user.skey in {key_dir}. Run: python scripts/generate_keys.py --name user")
        return 1
    if not dex.RECORD.exists():
        print("No deployment record; run scripts/deploy_dex.py --submit first.")
        return 1

    deployment = dex.load()
    amount_in = int(args.amount_ada * LOVELACE_PER_ADA)
    margin = int(args.margin_ada * LOVELACE_PER_ADA)
    deposit = amount_in + int(args.deposit_ada * LOVELACE_PER_ADA)
    order_address, _ = dex.addresses(deployment, Network.TESTNET)

    print(f"  order address  {order_address}")
    print(f"  sell           {args.amount_ada} ADA for at least {args.min_out:,} tokens")
    print(f"  margin         {args.margin_ada} ADA, plus a share of the batch's network fee")
    print(f"  locked         {deposit / LOVELACE_PER_ADA} ADA")
    if not args.submit:
        print("\nDRY RUN — nothing is submitted.")
        return 0
    if not settings.blockfrost_project_id:
        print("BLOCKFROST_PROJECT_ID is not set in .env.")
        return 1

    from blockfrost import ApiUrls
    from pycardano import BlockFrostChainContext

    from batcher.build.tx_builder import build_order_tx

    context = BlockFrostChainContext(settings.blockfrost_project_id, base_url=ApiUrls.preprod.value)
    if context.network != Network.TESTNET:
        raise SystemExit("the chain context is not a testnet; refusing to submit")
    skey = PaymentSigningKey.load(str(skey_path))
    tx = build_order_tx(context, skey, deployment, A_TO_B, amount_in, args.min_out, margin, deposit)
    context.submit_tx(tx)
    print(f"\n  submitted      {tx.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
