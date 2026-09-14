"""Plutus data mirroring ``onchain/lib/dex/types.ak`` constructor for constructor.

A datum encoded with the wrong constructor index or field order is not a type
error anywhere: it is a transaction the validator rejects on preprod, with no
explanation. ``tests/test_onchain.py`` therefore checks every class here against
the compiled blueprint, so the Python and Aiken definitions cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from pycardano import Address, Network, PlutusData, ScriptHash, VerificationKeyHash

# --- cardano/address ------------------------------------------------------------


@dataclass
class VerificationKeyCredential(PlutusData):
    CONSTR_ID = 0
    key_hash: bytes


@dataclass
class ScriptCredential(PlutusData):
    CONSTR_ID = 1
    script_hash: bytes


# typing.Union, not `X | Y`: PyCardano resolves these at runtime to pick a
# constructor while decoding, and it recognises typing.Union.
Credential = Union[VerificationKeyCredential, ScriptCredential]  # noqa: UP007


@dataclass
class InlineStake(PlutusData):
    """``Referenced.Inline``; pointer stake addresses are not supported."""

    CONSTR_ID = 0
    credential: Credential


@dataclass
class SomeStake(PlutusData):
    CONSTR_ID = 0
    stake: InlineStake


@dataclass
class NoStake(PlutusData):
    CONSTR_ID = 1


@dataclass
class PlutusAddress(PlutusData):
    CONSTR_ID = 0
    payment_credential: Credential
    stake_credential: Union[SomeStake, NoStake]  # noqa: UP007 — see Credential

    @classmethod
    def from_address(cls, address: Address) -> PlutusAddress:
        payment = _credential(address.payment_part)
        if address.staking_part is None:
            stake: SomeStake | NoStake = NoStake()
        else:
            stake = SomeStake(InlineStake(_credential(address.staking_part)))
        return cls(payment, stake)

    def to_address(self, network: Network = Network.TESTNET) -> Address:
        payment = _hash(self.payment_credential)
        staking = (
            _hash(self.stake_credential.stake.credential)
            if isinstance(self.stake_credential, SomeStake)
            else None
        )
        return Address(payment, staking, network=network)


def _credential(part) -> Credential:
    if isinstance(part, VerificationKeyHash):
        return VerificationKeyCredential(part.payload)
    if isinstance(part, ScriptHash):
        return ScriptCredential(part.payload)
    raise TypeError(f"unsupported address part: {type(part).__name__}")


def _hash(credential: Credential):
    if isinstance(credential, VerificationKeyCredential):
        return VerificationKeyHash(credential.key_hash)
    return ScriptHash(credential.script_hash)


# --- cardano/transaction ---------------------------------------------------------


@dataclass
class OutputRef(PlutusData):
    """An ``OutputReference``; the inline datum that tags each user payout."""

    CONSTR_ID = 0
    transaction_id: bytes
    output_index: int


# --- dex/types -----------------------------------------------------------------


@dataclass
class AtoB(PlutusData):
    """Sell lovelace for the pool token."""

    CONSTR_ID = 0


@dataclass
class BtoA(PlutusData):
    """Sell the pool token for lovelace."""

    CONSTR_ID = 1


Direction = Union[AtoB, BtoA]  # noqa: UP007 — see Credential


@dataclass
class OrderDatum(PlutusData):
    CONSTR_ID = 0
    owner: bytes
    return_address: PlutusAddress
    direction: Direction
    amount_in: int
    min_out: int
    margin: int


@dataclass
class Execute(PlutusData):
    CONSTR_ID = 0


@dataclass
class Cancel(PlutusData):
    CONSTR_ID = 1


@dataclass
class PoolDatum(PlutusData):
    CONSTR_ID = 0
    token_policy: bytes
    token_name: bytes
    nft_policy: bytes
    nft_name: bytes
    fee_bps: int


@dataclass
class PoolBatch(PlutusData):
    """The pool validator ignores its redeemer; any datum will do."""

    CONSTR_ID = 0
