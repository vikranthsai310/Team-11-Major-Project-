"""The deployed DEX's identity, derived from the batcher key (P7-6).

Everything about the deployment follows deterministically from two inputs: the
batcher's key hash and the slot after which minting closes. The minting policy is
"signed by the batcher **and** before slot S", so once S passes no second pool NFT
can ever exist — the NFT that identifies the pool is unique by construction, not by
the batcher's good behaviour.

The committed record holds hashes only. Compiled scripts are re-derived from the
key hash on load and checked against the recorded hashes, so a record and the
scripts that spend under it cannot silently disagree.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from pycardano import (
    Address,
    InvalidHereAfter,
    Network,
    ScriptAll,
    ScriptHash,
    ScriptPubkey,
    VerificationKeyHash,
)

from batcher.config.settings import ALLOWED_NETWORK
from batcher.onchain import blueprint
from batcher.onchain.blueprint import CompiledValidator
from batcher.onchain.datums import PoolDatum

TOKEN_NAME = b"TEAM11"
NFT_NAME = b"POOL"
DEFAULT_FEE_BPS = 30
RECORD = blueprint.ONCHAIN / "deployment.preprod.json"

Apply = Callable[[str, str, list], CompiledValidator]


class DeploymentMismatch(RuntimeError):
    """The scripts derived now do not hash to what the record says was deployed."""


@dataclass(frozen=True)
class Deployment:
    network: str
    batcher_key_hash: str
    mint_before_slot: int
    mint_policy_id: str
    token_name: str
    nft_name: str
    fee_bps: int
    order_script_hash: str
    pool_script_hash: str
    deploy_tx: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Deployment:
        return cls(**json.loads(text))


def mint_policy(batcher: VerificationKeyHash, before_slot: int) -> ScriptAll:
    """Batcher-signed and time-locked: nothing can be minted after ``before_slot``."""
    return ScriptAll([ScriptPubkey(batcher), InvalidHereAfter(before_slot)])


def derive(
    batcher: VerificationKeyHash,
    before_slot: int,
    fee_bps: int = DEFAULT_FEE_BPS,
    apply: Apply = blueprint.apply_parameters,
) -> tuple[Deployment, dict[str, CompiledValidator]]:
    policy_id = mint_policy(batcher, before_slot).hash()
    pool = apply("pool", "pool", [batcher.payload])
    order = apply("order", "order", [batcher.payload, policy_id.payload, TOKEN_NAME])
    deployment = Deployment(
        network=ALLOWED_NETWORK,
        batcher_key_hash=batcher.payload.hex(),
        mint_before_slot=before_slot,
        mint_policy_id=policy_id.payload.hex(),
        token_name=TOKEN_NAME.hex(),
        nft_name=NFT_NAME.hex(),
        fee_bps=fee_bps,
        order_script_hash=order.hash.payload.hex(),
        pool_script_hash=pool.hash.payload.hex(),
    )
    return deployment, {"order": order, "pool": pool}


def scripts_for(
    deployment: Deployment, apply: Apply = blueprint.apply_parameters
) -> dict[str, CompiledValidator]:
    """Re-derive the compiled scripts for a recorded deployment, and verify them."""
    _, scripts = derive(
        VerificationKeyHash(bytes.fromhex(deployment.batcher_key_hash)),
        deployment.mint_before_slot,
        deployment.fee_bps,
        apply,
    )
    for role, recorded in (
        ("order", deployment.order_script_hash),
        ("pool", deployment.pool_script_hash),
    ):
        if scripts[role].hash.payload.hex() != recorded:
            raise DeploymentMismatch(
                f"the {role} script derived now does not match the deployed one; "
                "was onchain/ rebuilt with different code?"
            )
    return scripts


def addresses(
    deployment: Deployment, network: Network = Network.TESTNET
) -> tuple[Address, Address]:
    """``(order_address, pool_address)``."""
    return (
        Address(ScriptHash(bytes.fromhex(deployment.order_script_hash)), network=network),
        Address(ScriptHash(bytes.fromhex(deployment.pool_script_hash)), network=network),
    )


def pool_datum(deployment: Deployment) -> PoolDatum:
    policy = bytes.fromhex(deployment.mint_policy_id)
    return PoolDatum(
        token_policy=policy,
        token_name=bytes.fromhex(deployment.token_name),
        nft_policy=policy,
        nft_name=bytes.fromhex(deployment.nft_name),
        fee_bps=deployment.fee_bps,
    )


def save(deployment: Deployment, path: Path = RECORD) -> Path:
    path.write_text(deployment.to_json(), encoding="utf-8")
    return path


def load(path: Path = RECORD) -> Deployment:
    return Deployment.from_json(path.read_text(encoding="utf-8"))
