"""M1 chain-data sources: Koios (primary, keyless) and Blockfrost (fallback).

Both return the same normalised :class:`BlockRecord`, so the collector is
indifferent to which one served a page and the two can be cross-checked against
each other field for field (``docs/04-MODULE-SPECS.md`` M1).

These endpoints serve **public mainnet block statistics** — sizes, slots and
transaction counts, no addresses and no personal data (``docs/05-DATA-SPEC.md``
§Ethics). That is deliberately unrelated to the preprod guard in
``batcher.config.settings``, which governs key material and transaction
submission; reading public block history loads no keys and signs nothing.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

KOIOS_BASE = "https://api.koios.rest/api/v1"
BLOCKFROST_BASE = "https://cardano-mainnet.blockfrost.io/api/v0"

MAX_PAGE = 1000

# Vertical filtering is not cosmetic here: asking Koios for only the seven fields
# D1 needs takes a 1,000-row page of deep history from ~73 s to ~12 s, which is
# the difference between an eight-hour collection and a ninety-minute one.
KOIOS_BLOCK_FIELDS = "block_height,abs_slot,block_time,block_size,tx_count,epoch_no,hash"

# Koios rejects larger bulk POST bodies with HTTP 413. Measured: /block_txs and
# /tx_info both accept 60 and both fail at 75, so 50 leaves headroom. Exceeding
# it is a permanent client error, not a rate limit — retrying cannot help, so it
# is checked here rather than discovered mid-collection.
KOIOS_BULK_MAX = 50

# Backoff schedule for HTTP 429, per docs/04-MODULE-SPECS.md M1: 1 s -> 60 s.
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 60.0
MAX_ATTEMPTS = 8


class SourceError(RuntimeError):
    """The source could not serve a page after exhausting its retries."""


@dataclass(frozen=True)
class BlockRecord:
    """One block, normalised across sources. Ordering fields only — no addresses."""

    block_height: int
    abs_slot: int
    block_time: int  # unix seconds, UTC
    block_size: int
    tx_count: int
    epoch_no: int
    block_hash: str


class BlockSource(Protocol):
    name: str

    def tip_height(self) -> int:
        """Height of the current chain tip."""

    def blocks_at_or_below(self, max_height: int, limit: int) -> list[BlockRecord]:
        """Up to ``limit`` blocks with height <= ``max_height``, newest first."""


def _request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 60.0,
    sleep=time.sleep,
) -> Any:
    """HTTP GET/POST returning parsed JSON, with exponential backoff on 429/5xx."""
    data = json.dumps(payload).encode() if payload is not None else None
    all_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        all_headers["Content-Type"] = "application/json"

    delay = BACKOFF_START_S
    last_error: Exception | None = None

    for _ in range(MAX_ATTEMPTS):
        request = urllib.request.Request(url, data=data, headers=all_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            last_error = exc
        except (
            urllib.error.URLError,
            TimeoutError,
            # A response can also be truncated *after* urlopen returns, which
            # surfaces during read() as IncompleteRead rather than as a URLError.
            # Left uncaught it aborts a collection that is otherwise fine to retry.
            http.client.HTTPException,
            ConnectionError,
        ) as exc:
            last_error = exc

        sleep(delay)
        delay = min(delay * 2, BACKOFF_MAX_S)

    raise SourceError(f"{url} failed after {MAX_ATTEMPTS} attempts: {last_error}")


def _check_bulk_size(items: list[str], endpoint: str) -> None:
    if len(items) > KOIOS_BULK_MAX:
        raise SourceError(
            f"{endpoint}: {len(items)} items exceeds the Koios bulk limit of "
            f"{KOIOS_BULK_MAX}; the server answers HTTP 413 and retrying will not help"
        )


class KoiosSource:
    """Primary source. No API key, PostgREST-style filtering."""

    name = "koios"

    def __init__(self, base: str = KOIOS_BASE, pause_s: float = 0.25, sleep=time.sleep):
        self.base = base.rstrip("/")
        self.pause_s = pause_s
        self._sleep = sleep

    def _get(self, path: str) -> Any:
        result = _request(f"{self.base}{path}", sleep=self._sleep)
        if self.pause_s:
            self._sleep(self.pause_s)
        return result

    def tip_height(self) -> int:
        rows = self._get("/blocks?limit=1&order=block_height.desc&block_height=not.is.null")
        return int(rows[0]["block_height"])

    def blocks_at_or_below(self, max_height: int, limit: int) -> list[BlockRecord]:
        rows = self._get(
            f"/blocks?block_height=lte.{max_height}"
            f"&order=block_height.desc&limit={min(limit, MAX_PAGE)}"
            f"&select={KOIOS_BLOCK_FIELDS}"
        )
        return normalise_koios(rows)

    def block_tx_hashes(self, block_hashes: list[str]) -> dict[str, list[str]]:
        """Transaction hashes per block, for the execution-unit sample (P1-6)."""
        _check_bulk_size(block_hashes, "block_txs")
        rows = _request(
            f"{self.base}/block_txs", payload={"_block_hashes": block_hashes}, sleep=self._sleep
        )
        if self.pause_s:
            self._sleep(self.pause_s)

        by_block: dict[str, list[str]] = {h: [] for h in block_hashes}
        for row in rows:
            by_block.setdefault(row["block_hash"], []).append(row["tx_hash"])
        return by_block

    def tx_info(self, tx_hashes: list[str]) -> list[dict[str, Any]]:
        """Raw transaction records, including ``tx_size`` and the fee actually paid."""
        _check_bulk_size(tx_hashes, "tx_info")
        rows = _request(
            f"{self.base}/tx_info",
            payload={
                "_tx_hashes": tx_hashes,
                "_inputs": False,
                "_metadata": False,
                "_assets": False,
                "_withdrawals": False,
                "_certs": False,
                "_scripts": True,
                "_bytecode": False,
            },
            sleep=self._sleep,
        )
        if self.pause_s:
            self._sleep(self.pause_s)
        return rows

    def tx_execution_units(self, tx_hashes: list[str]) -> dict[str, tuple[int, int]]:
        """``{tx_hash: (mem, steps)}`` summed over every redeemer in the transaction."""
        _check_bulk_size(tx_hashes, "tx_info")
        rows = _request(
            f"{self.base}/tx_info",
            payload={
                "_tx_hashes": tx_hashes,
                "_inputs": False,
                "_metadata": False,
                "_assets": False,
                "_withdrawals": False,
                "_certs": False,
                "_scripts": True,
                "_bytecode": False,
            },
            sleep=self._sleep,
        )
        if self.pause_s:
            self._sleep(self.pause_s)
        return {row["tx_hash"]: sum_redeemer_units(row) for row in rows}


class BlockfrostSource:
    """Fallback source. Requires a project ID matching the network being read."""

    name = "blockfrost"

    def __init__(
        self,
        project_id: str,
        base: str = BLOCKFROST_BASE,
        pause_s: float = 0.1,
        sleep=time.sleep,
    ):
        if not project_id:
            raise SourceError("BlockfrostSource requires a project id")
        self.base = base.rstrip("/")
        self.pause_s = pause_s
        self._headers = {"project_id": project_id}
        self._sleep = sleep

    def _get(self, path: str) -> Any:
        result = _request(f"{self.base}{path}", headers=self._headers, sleep=self._sleep)
        if self.pause_s:
            self._sleep(self.pause_s)
        return result

    def tip_height(self) -> int:
        return int(self._get("/blocks/latest")["height"])

    def blocks_at_or_below(self, max_height: int, limit: int) -> list[BlockRecord]:
        head = self._get(f"/blocks/{max_height}")
        rows = [head]
        remaining = min(limit, MAX_PAGE) - 1
        if remaining > 0:
            # /previous returns blocks *before* max_height, newest first.
            rows += self._get(f"/blocks/{max_height}/previous?count={min(remaining, 100)}")
        return normalise_blockfrost(rows[:limit])


def normalise_koios(rows: list[dict[str, Any]]) -> list[BlockRecord]:
    """Koios rows -> BlockRecord, dropping Byron epoch-boundary blocks.

    EBBs carry ``block_height`` and ``abs_slot`` of ``null`` and a size far above
    the modern block limit. They are not blocks in the sense this project means
    and would corrupt every congestion statistic, so they are excluded here
    rather than clipped downstream.
    """
    records = []
    for row in rows:
        if row.get("block_height") is None or row.get("abs_slot") is None:
            continue
        records.append(
            BlockRecord(
                block_height=int(row["block_height"]),
                abs_slot=int(row["abs_slot"]),
                block_time=int(row["block_time"]),
                block_size=int(row["block_size"]),
                tx_count=int(row["tx_count"]),
                epoch_no=int(row["epoch_no"]),
                block_hash=str(row["hash"]),
            )
        )
    return records


def normalise_blockfrost(rows: list[dict[str, Any]]) -> list[BlockRecord]:
    records = []
    for row in rows:
        if row.get("height") is None or row.get("slot") is None:
            continue
        records.append(
            BlockRecord(
                block_height=int(row["height"]),
                abs_slot=int(row["slot"]),
                block_time=int(row["time"]),
                block_size=int(row["size"]),
                tx_count=int(row["tx_count"]),
                epoch_no=int(row["epoch"]),
                block_hash=str(row["hash"]),
            )
        )
    return records


def sum_redeemer_units(tx_info_row: dict[str, Any]) -> tuple[int, int]:
    """Total (memory, steps) across a transaction's Plutus redeemers.

    Koios nests these at ``plutus_contracts[].input.redeemer.unit``. A
    transaction with no Plutus scripts genuinely consumes zero execution units,
    which is different from a block whose units were never collected — that
    distinction is carried by ``exunits_source``, never by a zero (ADR-005).
    """
    mem = steps = 0
    for contract in tx_info_row.get("plutus_contracts") or []:
        unit = ((contract.get("input") or {}).get("redeemer") or {}).get("unit") or {}
        mem += int(unit.get("mem") or 0)
        steps += int(unit.get("steps") or 0)
    return mem, steps


def compare_sources(a: list[BlockRecord], b: list[BlockRecord]) -> list[str]:
    """Field-level disagreements between two sources over the same heights.

    A persistent mismatch is a defect (``docs/04-MODULE-SPECS.md`` M1); Koios is
    preferred and the discrepancy is logged.
    """
    by_height = {record.block_height: record for record in b}
    differences = []
    for record in a:
        other = by_height.get(record.block_height)
        if other is None:
            continue
        if record != other:
            differences.append(f"height {record.block_height}: {record} != {other}")
    return differences
