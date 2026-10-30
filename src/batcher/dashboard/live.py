"""The Live view: the deployed DEX on preprod, read through Blockfrost (P7-12).

Kept free of numpy and pandas so it can run on its own, in the hosted build's
serverless function, as well as inside the local dashboard.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEMO_MANIFEST = REPO / "experiments" / "phase7-preprod-demo" / "manifest.json"
EXPLORER = "https://preprod.cardanoscan.io"


def clean(value):
    """Strict JSON: NaN and infinities become null."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def recorded_transactions(manifest: Path | None = DEMO_MANIFEST) -> list[dict]:
    if manifest is None or not manifest.exists():
        return []
    record = json.loads(manifest.read_text())
    steps = [
        ("deploy_tx", "Deploy the DEX", "Minted TEAM11 and the POOL NFT; opened the pool"),
        ("funding_tx", "Fund the demo user", "50 tADA from the batcher key to the user key"),
        ("order_tx", "User places an order", "Sell 10 tADA for at least 85,000 TEAM11"),
        ("batch_tx", "Batcher settles the order", "Live P2 batch; user received 90,661 TEAM11"),
    ]
    return [
        {
            "step": title,
            "detail": detail,
            "tx": record[key],
            "url": f"{EXPLORER}/transaction/{record[key]}",
        }
        for key, title, detail in steps
        if record.get(key)
    ]


def live_payload(context, deployment, manifest: Path | None = DEMO_MANIFEST) -> dict:
    """The deployed DEX as it stands on chain now."""
    from pycardano import Address, Network, VerificationKeyHash

    from batcher.build.tx_builder import PoolNotFound, _coin, _quantity, read_orders, read_pool
    from batcher.onchain.deployment import addresses

    order_address, pool_address = addresses(deployment, Network.TESTNET)
    batcher = Address(
        VerificationKeyHash(bytes.fromhex(deployment.batcher_key_hash)), network=Network.TESTNET
    )

    pool = None
    try:
        utxo = read_pool(context.utxos(pool_address), deployment)
        lovelace = _coin(utxo.output.amount)
        tokens = _quantity(utxo.output.amount, deployment, deployment.token_name)
        pool = {
            "ada": lovelace / 1_000_000,
            "tokens": tokens,
            "tokens_per_ada": tokens / (lovelace / 1_000_000) if lovelace else None,
            "nft": _quantity(utxo.output.amount, deployment, deployment.nft_name),
            "utxo": f"{utxo.input.transaction_id}#{utxo.input.index}",
            "url": f"{EXPLORER}/transaction/{utxo.input.transaction_id}",
        }
    except PoolNotFound:
        pool = None

    orders = [
        {
            "ref": f"{o.tx_hash}#{o.index}",
            "url": f"{EXPLORER}/transaction/{o.tx_hash}",
            "direction": o.direction,
            "amount_in": o.amount_in,
            "min_out": o.min_out,
            "margin": o.margin,
            "locked_ada": o.lovelace / 1_000_000,
        }
        for _, o in read_orders(context.utxos(order_address), deployment, Network.TESTNET)
    ]
    batcher_ada = sum(_coin(u.output.amount) for u in context.utxos(batcher)) / 1_000_000

    return clean(
        {
            "available": True,
            "network": "preprod",
            "tip_slot": context.last_block_slot,
            "fee_bps": deployment.fee_bps,
            "token": bytes.fromhex(deployment.token_name).decode(),
            "policy_id": deployment.mint_policy_id,
            "addresses": {
                "pool": str(pool_address),
                "order": str(order_address),
                "batcher": str(batcher),
            },
            "address_url": f"{EXPLORER}/address/",
            "pool": pool,
            "orders": orders,
            "batcher_ada": batcher_ada,
            "transactions": recorded_transactions(manifest),
        }
    )


class LiveSource:  # pragma: no cover - network
    """Blockfrost-backed live view, cached so a busy screen cannot exhaust the free tier."""

    def __init__(self, ttl_seconds: float = 15.0, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl_seconds
        self.clock = clock
        self._cached: tuple[float, dict] | None = None
        self._context = None

    def __call__(self) -> dict:
        now = self.clock()
        if self._cached and now - self._cached[0] < self.ttl:
            return self._cached[1]
        try:
            from blockfrost import ApiUrls
            from pycardano import BlockFrostChainContext, Network

            from batcher.config.settings import load_settings
            from batcher.onchain import deployment as dex

            settings = load_settings()
            if not settings.blockfrost_project_id:
                raise RuntimeError("BLOCKFROST_PROJECT_ID is not set in .env")
            if not dex.RECORD.exists():
                raise RuntimeError("no deployment record; the DEX has not been deployed")
            if self._context is None:
                self._context = BlockFrostChainContext(
                    settings.blockfrost_project_id, base_url=ApiUrls.preprod.value
                )
                if self._context.network != Network.TESTNET:
                    raise RuntimeError("not a testnet context")
            payload = live_payload(self._context, dex.load())
        except Exception as error:
            payload = {
                "available": False,
                "reason": f"{type(error).__name__}: {error}",
                "transactions": recorded_transactions(),
            }
        self._cached = (now, payload)
        return payload
