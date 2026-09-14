"""The chain as the live batcher sees it: a narrow port, and its Blockfrost adapter.

The daemon depends only on :class:`LiveChain`, so every behaviour it has — one
decision per block, head-of-line waiting, expiry, shutdown — is tested offline
against a fake. Only the thin adapter below talks to the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pycardano import Transaction, UTxO

from batcher.config.protocol import MAX_BLOCK_SIZE


@dataclass(frozen=True)
class Tip:
    height: int
    slot: int
    fill: float


class LiveChain(Protocol):
    context: object

    def tip(self) -> Tip: ...

    def recent_fills(self, count: int) -> list[float]:
        """Size-based fill of the last ``count`` blocks, oldest first."""

    def utxos(self, address) -> list[UTxO]: ...

    def arrival_slot(self, tx_hash: str) -> int:
        """Slot at which the transaction creating an order was included."""

    def submit(self, tx: Transaction) -> str: ...

    def inclusion_slot(self, tx_hash: str) -> int | None:
        """Slot of inclusion, or ``None`` while the transaction is not on chain."""


class BlockfrostChain:  # pragma: no cover - network adapter, exercised live only
    def __init__(self, context):
        self.context = context
        self.api = context.api

    def tip(self) -> Tip:
        block = self.api.block_latest()
        return Tip(int(block.height), int(block.slot), int(block.size) / MAX_BLOCK_SIZE)

    def recent_fills(self, count: int) -> list[float]:
        latest = self.api.block_latest()
        previous = list(self.api.blocks_previous(latest.hash, count=max(count - 1, 1)))
        blocks = sorted([*previous, latest], key=lambda b: int(b.height))
        return [int(b.size) / MAX_BLOCK_SIZE for b in blocks[-count:]]

    def utxos(self, address) -> list[UTxO]:
        return self.context.utxos(address)

    def arrival_slot(self, tx_hash: str) -> int:
        return int(self.api.transaction(tx_hash).slot)

    def submit(self, tx: Transaction) -> str:
        self.context.submit_tx(tx)
        return str(tx.id)

    def inclusion_slot(self, tx_hash: str) -> int | None:
        from blockfrost import ApiError

        try:
            return int(self.api.transaction(tx_hash).slot)
        except ApiError as error:
            if getattr(error, "status_code", None) == 404:
                return None
            raise
