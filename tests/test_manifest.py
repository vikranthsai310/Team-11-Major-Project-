"""P0-11 — a result without a manifest is not a result (docs/02 §9, NFR-3)."""

from __future__ import annotations

import json

from batcher.config import protocol
from batcher.eval.manifest import config_hash, write_manifest


def test_manifest_records_what_is_needed_to_reproduce_a_run(tmp_path):
    path = write_manifest(
        "phase0-smoke",
        seed=42,
        dataset_checksum="deadbeef",
        root=tmp_path,
        policy="null",
    )

    manifest = json.loads(path.read_text())

    assert manifest["seed"] == 42
    assert manifest["dataset_checksum"] == "deadbeef"
    assert manifest["policy"] == "null"
    assert manifest["config_hash"] == config_hash()
    assert manifest["protocol"]["MAX_TX_SIZE"] == protocol.MAX_TX_SIZE
    assert manifest["params"]["D_MAX"]
    assert "sha" in manifest["git"]
    assert manifest["created_utc"]


def test_config_hash_is_stable_across_calls():
    assert config_hash() == config_hash()


def test_manifest_lands_under_the_experiment_id(tmp_path):
    path = write_manifest("exp-001", seed=0, root=tmp_path)
    assert path == tmp_path / "exp-001" / "manifest.json"
