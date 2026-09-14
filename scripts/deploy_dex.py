"""P7-6 · Deploy the DEX to preprod. **Dry run unless ``--submit`` is given.**

    python scripts/deploy_dex.py                 # derive and print the deployment; no network
    python scripts/deploy_dex.py --submit        # build, sign and submit to preprod

Prerequisites for ``--submit``: ``batcher.skey`` from ``scripts/generate_keys.py``,
the batcher address funded from the preprod faucet, and ``BLOCKFROST_PROJECT_ID``
for a **preprod** project in ``.env``. The settings guard refuses any other network.

What it does: mints the ``TEAM11`` supply and a single ``POOL`` NFT under a policy
that closes after ``--mint-window-slots``, and opens the pool at the pool script
with ``--pool-ada`` and ``--pool-tokens`` of liquidity. The deployment record
(hashes only) is written to ``onchain/deployment.preprod.json``.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from pycardano import Network, PaymentSigningKey

from batcher.config.settings import load_settings
from batcher.onchain import deployment as dex

LOVELACE_PER_ADA = 1_000_000


def load_batcher_key(key_dir: Path) -> PaymentSigningKey | None:
    path = key_dir / "batcher.skey"
    return PaymentSigningKey.load(str(path)) if path.exists() else None


def describe(deployment: dex.Deployment, pool_ada: float, pool_tokens: int, supply: int) -> str:
    order_address, pool_address = dex.addresses(deployment, Network.TESTNET)
    return "\n".join(
        [
            f"  batcher key hash   {deployment.batcher_key_hash}",
            f"  mint policy        {deployment.mint_policy_id}",
            f"  minting closes     after slot {deployment.mint_before_slot}",
            f"  token / NFT        {bytes.fromhex(deployment.token_name).decode()} / "
            f"{bytes.fromhex(deployment.nft_name).decode()}",
            f"  pool fee           {deployment.fee_bps} bps",
            f"  order script       {deployment.order_script_hash}",
            f"  pool script        {deployment.pool_script_hash}",
            f"  order address      {order_address}",
            f"  pool address       {pool_address}",
            f"  liquidity          {pool_ada:,.0f} ADA + {pool_tokens:,} tokens",
            f"  minted supply      {supply:,} tokens",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-dir", type=Path, default=None)
    parser.add_argument("--pool-ada", type=float, default=100.0)
    parser.add_argument("--pool-tokens", type=int, default=1_000_000)
    parser.add_argument("--supply", type=int, default=10_000_000)
    parser.add_argument("--fee-bps", type=int, default=dex.DEFAULT_FEE_BPS)
    parser.add_argument("--mint-window-slots", type=int, default=7_200)
    parser.add_argument("--assume-slot", type=int, default=0, help="dry run only")
    parser.add_argument("--submit", action="store_true", help="submit to preprod")
    parser.add_argument("--redeploy", action="store_true", help="replace an existing record")
    args = parser.parse_args(argv)

    settings = load_settings()  # refuses anything but preprod
    key_dir = args.key_dir or settings.batcher_key_dir
    skey = load_batcher_key(key_dir)
    if skey is None:
        print(f"No batcher.skey in {key_dir}. Run: python scripts/generate_keys.py --name batcher")
        return 1
    batcher = skey.to_verification_key().hash()
    pool_lovelace = int(args.pool_ada * LOVELACE_PER_ADA)

    if not args.submit:
        before = args.assume_slot + args.mint_window_slots
        deployment, _ = dex.derive(batcher, before, args.fee_bps)
        print("DRY RUN — nothing is submitted.\n")
        print(describe(deployment, args.pool_ada, args.pool_tokens, args.supply))
        print(
            "\nThe pool script depends only on the batcher key. The mint policy, and so the "
            "order script, depend on the mint window, which --submit sets from the live tip."
        )
        return 0

    if dex.RECORD.exists() and not args.redeploy:
        print(f"{dex.RECORD} exists; a second deployment would orphan it. Use --redeploy.")
        return 1
    if not settings.blockfrost_project_id:
        print("BLOCKFROST_PROJECT_ID is not set in .env (a preprod project is required).")
        return 1

    from blockfrost import ApiUrls
    from pycardano import BlockFrostChainContext

    from batcher.build.tx_builder import build_deploy_tx

    context = BlockFrostChainContext(settings.blockfrost_project_id, base_url=ApiUrls.preprod.value)
    if context.network != Network.TESTNET:
        raise SystemExit("the chain context is not a testnet; refusing to submit")

    before = context.last_block_slot + args.mint_window_slots
    deployment, _ = dex.derive(batcher, before, args.fee_bps)
    tx = build_deploy_tx(context, skey, deployment, pool_lovelace, args.pool_tokens, args.supply)

    print(describe(deployment, args.pool_ada, args.pool_tokens, args.supply))
    print(f"\n  fee                {tx.transaction_body.fee:,} lovelace")
    context.submit_tx(tx)
    print(f"  submitted          {tx.id}")

    record = dex.save(replace(deployment, deploy_tx=str(tx.id)))
    print(f"\nrecord {record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
