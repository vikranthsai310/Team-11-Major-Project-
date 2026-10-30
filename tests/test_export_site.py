"""The hosted dashboard build (scripts/export_site.py): what it publishes and how it routes."""

from __future__ import annotations

import importlib.util
import json
import re
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = _load("export_site", REPO_ROOT / "scripts" / "export_site.py")


def test_episodes_are_spread_and_include_the_busiest_day():
    congested = [0.0] * 100
    congested[37] = 0.9
    chosen = export.pick_episodes(congested, 10)
    assert len(chosen) == 10
    assert 37 in chosen
    assert chosen[0] == 0
    assert chosen == sorted(set(chosen))


def test_episode_count_is_clamped():
    assert export.pick_episodes([0.1, 0.2, 0.3], 10) == [0, 1, 2]
    assert len(export.pick_episodes([0.1] * 5, 1)) == 1


def test_requirements_pin_the_function_closure():
    pins = export.pinned_requirements()
    names = {p.split("==")[0] for p in pins}
    assert {"pycardano", "blockfrost-python", "cbor2", "requests"} <= names
    assert all(re.fullmatch(r"[a-z0-9.-]+==\S+", p) for p in pins)
    # the function must stay small: none of the ML stack may be pulled in
    assert not names & {"numpy", "pandas", "torch", "lightgbm", "scipy"}


def test_replay_rewrite_only_accepts_safe_parameters():
    rewrite = next(r for r in export.vercel_config()["rewrites"] if r["source"] == "/api/replay")
    patterns = {h["key"]: h["value"] for h in rewrite["has"]}

    def accepts(key, value):
        # Vercel matches the whole query value against the pattern
        return re.fullmatch(patterns[key].replace("?<", "?P<"), value) is not None

    assert accepts("policy", "p2") and accepts("rate", "heavy") and accepts("episode", "37")
    for key, value in [("policy", "../x"), ("rate", "a/b"), ("episode", "1.json"), ("policy", "")]:
        assert not accepts(key, value)


def test_security_headers_forbid_inline_scripts_and_framing():
    headers = {h["key"]: h["value"] for h in export.SECURITY_HEADERS}
    csp = headers["Content-Security-Policy"]
    assert "script-src 'self';" in csp
    assert "frame-ancestors 'none'" in csp
    assert headers["X-Frame-Options"] == "DENY"


def test_the_function_never_ships_the_static_data():
    excluded = export.vercel_config()["functions"]["api/live.py"]["excludeFiles"]
    assert "data/**" in excluded


def test_the_function_refuses_query_strings_before_reading_the_chain(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "live.py").write_text(export.LIVE_FUNCTION, encoding="utf-8")
    function = _load("live_fn", tmp_path / "api" / "live.py")
    calls = []
    function.SOURCE = lambda: calls.append(1) or {"available": False, "reason": "secret detail"}

    server = ThreadingHTTPServer(("127.0.0.1", 0), function.handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/api/live"
    try:
        with pytest.raises(HTTPError) as refused:
            urlopen(base + "?bust=1", timeout=10)
        assert refused.value.code == 400
        assert calls == []

        payload = json.loads(urlopen(base, timeout=10).read())
        assert calls == [1]
        assert payload["reason"] == "the chain could not be read just now"  # detail stays in logs
    finally:
        server.shutdown()
