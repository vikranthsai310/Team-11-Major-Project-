"""P7-12 — the dashboard shows the project's own numbers, and only on localhost."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest
from pycardano import Network, PaymentSigningKey, Value

from batcher.dashboard import data
from batcher.dashboard.server import DashboardProvider, serve
from batcher.data.collector import collect_blocks
from batcher.data.features import preprocess
from batcher.forecast.baseline import MovingAverage
from batcher.policy.static import Greedy
from batcher.sim.env import run_episode
from batcher.sim.orders import ArrivalProcess, OrderStream
from conftest import BASE_HEIGHT, FakeSource, make_records


@pytest.fixture(scope="module")
def replay(tmp_path_factory):
    source = FakeSource(make_records(500, seed=61))
    blocks = preprocess(
        collect_blocks(
            source,
            start_height=BASE_HEIGHT,
            end_height=source.tip_height(),
            staging_dir=tmp_path_factory.mktemp("staging"),
            page_size=250,
        )
    )
    process = ArrivalProcess(base_per_slot=0.15, diurnal=tuple([1.0] * 24), bursts_per_day=0.0)
    stream = OrderStream(
        process=process, rng=np.random.default_rng(7), rate_multiplier=1.0, episode_id="t"
    )
    result = run_episode(
        blocks, Greedy(), stream, np.random.default_rng(8), episode_id="t", policy_name="e3"
    )
    forecast = data.forecast_series(blocks, MovingAverage(horizon=3))
    payload = data.episode_payload(
        blocks,
        result,
        forecast,
        policy_key="e3",
        policy_label="E3 · greedy",
        episode_id="t",
        rate="matched",
    )
    return blocks, result, payload


# --- Run view -------------------------------------------------------------------------------


def test_the_replay_is_the_simulators_decision_log(replay):
    _, result, payload = replay
    column = {name: i for i, name in enumerate(payload["columns"])}
    assert len(payload["rows"]) == len(result.decisions)
    assert sum(row[column["submit"]] for row in payload["rows"]) == len(result.submissions)
    assert len(payload["settled"]) == len(result.settled)


def test_no_decision_is_shown_while_the_pool_is_locked(replay):
    _, _, payload = replay
    column = {name: i for i, name in enumerate(payload["columns"])}
    locked = [row for row in payload["rows"] if row[column["locked"]]]
    assert locked, "a greedy replay should hold the pool at some point"
    assert all(row[column["submit"]] == 0 for row in locked)


def test_gate_b_is_never_above_gate_a(replay):
    _, _, payload = replay
    column = {name: i for i, name in enumerate(payload["columns"])}
    for row in payload["rows"]:
        a, b = row[column["gate_a"]], row[column["gate_b"]]
        if a is not None and b is not None:
            assert 0 <= b <= a


def test_the_replay_payload_is_strict_json(replay):
    _, _, payload = replay
    json.dumps(payload, allow_nan=False)
    assert payload["settled"] == sorted(payload["settled"], key=lambda pair: pair[1])


# --- Compare view -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def results():
    if not (data.EVALUATION / "episode_metrics.parquet").exists():
        pytest.skip("the test-split evaluation is not present")
    return data.compare_payload()


def test_compare_reports_every_policy_at_every_rate(results):
    assert set(results["rates"]) == {"light", "matched", "heavy"}
    for rows in results["rates"].values():
        assert [r["key"] for r in rows] == data.POLICY_ORDER
        for row in rows:
            for metric in data.TABLE_METRICS:
                median, low, high = row[metric]
                if median is not None:
                    assert low <= median <= high


def test_compare_matches_the_reported_table(results):
    """Report Table 8.4: P2 N=4 at the matched rate has a median L-p95 of 125.0 slots."""
    p2 = next(r for r in results["rates"]["matched"] if r["key"] == "p2(D=120,N=4)")
    assert p2["l_p95"][0] == pytest.approx(125.0)
    assert results["gate_a_violations"] == 0


def test_the_latency_distribution_is_monotone(results):
    for quantiles in results["cdf_matched"].values():
        assert len(quantiles) == 101
        assert quantiles == sorted(quantiles)
    json.dumps(results, allow_nan=False)


# --- Live view ------------------------------------------------------------------------------------


def test_live_view_reads_the_pool_and_queue_from_the_chain():
    from batcher.build.tx_builder import key_address
    from batcher.onchain import deployment as dex
    from test_tx_builder import TIP, FakeChain, order_utxo, pool_utxo, unapplied

    chain = FakeChain()
    batcher = PaymentSigningKey.generate()
    user = PaymentSigningKey.generate()
    deployment, _ = dex.derive(batcher.to_verification_key().hash(), TIP + 3_600, apply=unapplied)
    chain.add(key_address(batcher, chain), Value(40_000_000), tx_byte=0xB0)
    pool_utxo(chain, deployment)
    order_utxo(chain, deployment, user, 0)

    payload = data.live_payload(chain, deployment, manifest=None)
    assert payload["available"] and payload["pool"]["nft"] == 1
    assert payload["pool"]["ada"] == 1_000 and payload["pool"]["tokens"] == 1_000_000
    assert len(payload["orders"]) == 1 and payload["orders"][0]["min_out"] == 9_000
    assert payload["batcher_ada"] == 40
    assert payload["addresses"]["pool"].startswith("addr_test1")
    assert Network.TESTNET.name == "TESTNET"
    json.dumps(payload, allow_nan=False)


def test_recorded_swap_transactions_link_to_the_preprod_explorer():
    if not data.DEMO_MANIFEST.exists():
        pytest.skip("no preprod demo recorded")
    steps = data.recorded_transactions()
    assert [s["step"] for s in steps][-1] == "Batcher settles the order"
    assert all(s["url"].startswith("https://preprod.cardanoscan.io/transaction/") for s in steps)


# --- server ------------------------------------------------------------------------------


class StubLibrary:
    def catalogue(self):
        return {"state": "loading", "message": "", "policies": [], "rates": [], "episodes": []}

    def replay(self, policy, rate, index):
        raise data.NotReady("still loading")


@pytest.fixture
def server():
    provider = DashboardProvider(
        StubLibrary(),
        live=lambda: {"available": False, "reason": "offline", "transactions": []},
        compare=lambda: {"rates": {}, "value": 1},
    )
    httpd = serve(provider, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_the_page_and_its_assets_are_served(server):
    status, body = get(f"{server}/")
    assert status == 200 and b"<title>Adaptive Batcher" in body
    assert get(f"{server}/static/app.js")[0] == 200
    assert get(f"{server}/static/style.css")[0] == 200


def test_the_api_returns_json_and_reports_loading_honestly(server):
    status, body = get(f"{server}/api/compare")
    assert status == 200 and json.loads(body)["value"] == 1
    assert json.loads(get(f"{server}/api/catalogue")[1])["state"] == "loading"
    assert get(f"{server}/api/replay?policy=p2&rate=matched&episode=0")[0] == 503
    assert get(f"{server}/api/replay?episode=nope")[0] == 400


def test_nothing_outside_the_static_folder_is_served(server):
    assert get(f"{server}/static/../server.py")[0] == 404
    assert get(f"{server}/static/..%2Fserver.py")[0] == 404
    assert get(f"{server}/etc/passwd")[0] == 404


def test_the_dashboard_refuses_to_listen_beyond_localhost():
    with pytest.raises(ValueError, match="localhost-only"):
        serve(DashboardProvider(StubLibrary(), live=dict, compare=dict), "0.0.0.0", 0)
