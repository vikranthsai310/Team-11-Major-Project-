"""P1-1 — source normalisation, the EBB guard, backoff and cross-source comparison."""

from __future__ import annotations

import dataclasses
import http.client
import urllib.error

import pytest

from batcher.data import sources
from batcher.data.sources import (
    BlockRecord,
    SourceError,
    compare_sources,
    normalise_blockfrost,
    normalise_koios,
    sum_redeemer_units,
)

KOIOS_ROW = {
    "hash": "6c79",
    "epoch_no": 655,
    "abs_slot": 197726176,
    "block_height": 13934990,
    "block_size": 6553,
    "block_time": 1789292467,
    "tx_count": 8,
}

# A real Byron epoch-boundary block as Koios serves it: no height, no slot, and a
# size seven times the modern block limit.
BYRON_EBB_ROW = {
    "hash": "fd90",
    "epoch_no": 137,
    "abs_slot": None,
    "block_height": None,
    "block_size": 648090,
    "block_time": 1550000000,
    "tx_count": 0,
}

BLOCKFROST_ROW = {
    "hash": "6c79",
    "epoch": 655,
    "slot": 197726176,
    "height": 13934990,
    "size": 6553,
    "time": 1789292467,
    "tx_count": 8,
}


def test_koios_row_normalises():
    (record,) = normalise_koios([KOIOS_ROW])
    assert record.block_height == 13934990
    assert record.abs_slot == 197726176
    assert record.block_size == 6553


def test_byron_epoch_boundary_blocks_are_excluded():
    """They would otherwise produce fill_pct > 7 and corrupt every congestion statistic."""
    assert normalise_koios([BYRON_EBB_ROW]) == []
    assert len(normalise_koios([BYRON_EBB_ROW, KOIOS_ROW])) == 1


def test_the_two_sources_agree_field_for_field():
    """M1: a persistent Koios/Blockfrost mismatch is a defect."""
    koios = normalise_koios([KOIOS_ROW])
    blockfrost = normalise_blockfrost([BLOCKFROST_ROW])
    assert koios == blockfrost
    assert compare_sources(koios, blockfrost) == []


def test_source_disagreement_is_reported():
    koios = normalise_koios([KOIOS_ROW])
    altered = normalise_blockfrost([{**BLOCKFROST_ROW, "size": 9999}])
    assert compare_sources(koios, altered)


def test_execution_units_sum_over_every_redeemer():
    tx = {
        "plutus_contracts": [
            {"input": {"redeemer": {"unit": {"mem": "839187", "steps": "205253204"}}}},
            {"input": {"redeemer": {"unit": {"mem": "100000", "steps": "1000000"}}}},
        ]
    }
    assert sum_redeemer_units(tx) == (939187, 206253204)


def test_a_transaction_without_plutus_scripts_consumes_nothing():
    assert sum_redeemer_units({"plutus_contracts": []}) == (0, 0)
    assert sum_redeemer_units({}) == (0, 0)


def test_rate_limiting_backs_off_then_succeeds(monkeypatch):
    """HTTP 429 is expected on a free tier; it must back off, not fail."""
    slept: list[float] = []
    attempts = {"n": 0}

    class Response:
        def read(self):
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
        return Response()

    monkeypatch.setattr(sources.urllib.request, "urlopen", fake_urlopen)

    assert sources._request("https://example/x", sleep=slept.append) == []
    assert attempts["n"] == 3
    assert slept == [1.0, 2.0]  # exponential, starting at 1 s


def test_a_truncated_response_is_retried(monkeypatch):
    """Observed in a real collection: IncompleteRead aborted a 57 %-complete sample.

    It is raised by read(), after urlopen has already succeeded, so it is not a
    URLError and was not covered by the original retry set.
    """
    attempts = {"n": 0}

    class Response:
        def read(self):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise http.client.IncompleteRead(b"partial", 12977)
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **k: Response())

    assert sources._request("https://example/x", sleep=lambda _: None) == []
    assert attempts["n"] == 3


def test_a_dropped_connection_is_retried(monkeypatch):
    attempts = {"n": 0}

    def flaky(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ConnectionResetError("connection reset by peer")
        raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)

    monkeypatch.setattr(sources.urllib.request, "urlopen", flaky)

    with pytest.raises(SourceError):
        sources._request("https://example/x", sleep=lambda _: None)
    assert attempts["n"] == sources.MAX_ATTEMPTS


def test_backoff_gives_up_with_a_clear_error(monkeypatch):
    def always_429(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(sources.urllib.request, "urlopen", always_429)

    with pytest.raises(SourceError):
        sources._request("https://example/x", sleep=lambda _: None)


def test_client_errors_are_not_retried(monkeypatch):
    def not_found(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(sources.urllib.request, "urlopen", not_found)

    with pytest.raises(urllib.error.HTTPError):
        sources._request("https://example/x", sleep=lambda _: None)


@pytest.mark.parametrize("method", ["block_tx_hashes", "tx_execution_units"])
def test_oversized_bulk_requests_fail_before_the_network(monkeypatch, method):
    """Koios answers HTTP 413 above ~60 items; that is permanent, so catch it locally."""
    called = False

    def should_not_run(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(sources, "_request", should_not_run)
    source = sources.KoiosSource(pause_s=0, sleep=lambda _: None)

    with pytest.raises(SourceError, match="bulk limit"):
        getattr(source, method)(["x"] * (sources.KOIOS_BULK_MAX + 1))
    assert not called


def test_bulk_requests_at_the_limit_are_allowed(monkeypatch):
    _capture_requests(monkeypatch, [])
    source = sources.KoiosSource(pause_s=0, sleep=lambda _: None)
    assert source.tx_execution_units(["x"] * sources.KOIOS_BULK_MAX) == {}


def test_blockfrost_requires_a_project_id():
    with pytest.raises(SourceError):
        sources.BlockfrostSource("")


def _capture_requests(monkeypatch, response):
    """Replace the HTTP layer, recording the URLs and payloads asked for."""
    calls: list[tuple[str, dict | None]] = []

    def fake_request(url, *, headers=None, payload=None, timeout=60.0, sleep=None):
        calls.append((url, payload))
        return response(url, payload) if callable(response) else response

    monkeypatch.setattr(sources, "_request", fake_request)
    return calls


def test_koios_pages_by_height_range_and_requests_only_the_needed_columns(monkeypatch):
    """Offset paging would return different rows on every run; select= keeps it fast."""
    calls = _capture_requests(monkeypatch, [KOIOS_ROW])
    source = sources.KoiosSource(pause_s=0, sleep=lambda _: None)

    source.blocks_at_or_below(13934990, 1000)
    url, _ = calls[0]

    assert "block_height=lte.13934990" in url
    assert "order=block_height.desc" in url
    assert "offset=" not in url
    assert f"select={sources.KOIOS_BLOCK_FIELDS}" in url


def test_koios_page_size_is_capped_at_the_api_maximum(monkeypatch):
    calls = _capture_requests(monkeypatch, [])
    source = sources.KoiosSource(pause_s=0, sleep=lambda _: None)

    source.blocks_at_or_below(100, 50_000)
    assert f"limit={sources.MAX_PAGE}" in calls[0][0]


def test_koios_tip_excludes_null_height_rows(monkeypatch):
    """Ordering by height descending puts the null-height Byron EBBs first."""
    calls = _capture_requests(monkeypatch, [KOIOS_ROW])
    source = sources.KoiosSource(pause_s=0, sleep=lambda _: None)

    assert source.tip_height() == 13934990
    assert "block_height=not.is.null" in calls[0][0]


def test_koios_groups_transaction_hashes_by_block(monkeypatch):
    rows = [
        {"block_hash": "a", "tx_hash": "t1"},
        {"block_hash": "a", "tx_hash": "t2"},
        {"block_hash": "b", "tx_hash": "t3"},
    ]
    _capture_requests(monkeypatch, rows)
    source = sources.KoiosSource(pause_s=0, sleep=lambda _: None)

    assert source.block_tx_hashes(["a", "b"]) == {"a": ["t1", "t2"], "b": ["t3"]}


def test_koios_blocks_with_no_transactions_come_back_empty(monkeypatch):
    _capture_requests(monkeypatch, [])
    source = sources.KoiosSource(pause_s=0, sleep=lambda _: None)
    assert source.block_tx_hashes(["a"]) == {"a": []}


def test_koios_execution_units_are_summed_per_transaction(monkeypatch):
    rows = [
        {
            "tx_hash": "t1",
            "plutus_contracts": [{"input": {"redeemer": {"unit": {"mem": "100", "steps": "200"}}}}],
        },
        {"tx_hash": "t2", "plutus_contracts": []},
    ]
    _capture_requests(monkeypatch, rows)
    source = sources.KoiosSource(pause_s=0, sleep=lambda _: None)

    assert source.tx_execution_units(["t1", "t2"]) == {"t1": (100, 200), "t2": (0, 0)}


def test_blockfrost_fetches_the_head_block_then_its_predecessors(monkeypatch):
    def respond(url, payload):
        if url.endswith("/previous?count=2"):
            return [{**BLOCKFROST_ROW, "height": 13934989}, {**BLOCKFROST_ROW, "height": 13934988}]
        return BLOCKFROST_ROW

    calls = _capture_requests(monkeypatch, respond)
    source = sources.BlockfrostSource("token", pause_s=0, sleep=lambda _: None)

    records = source.blocks_at_or_below(13934990, 3)
    assert [record.block_height for record in records] == [13934990, 13934989, 13934988]
    assert calls[0][0].endswith("/blocks/13934990")


def test_block_record_is_hashable_and_frozen():
    record = BlockRecord(1, 2, 3, 4, 5, 6, "h")
    assert hash(record)
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.block_size = 9
