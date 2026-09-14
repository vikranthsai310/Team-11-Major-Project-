"""P7-5 — keys are generated outside the repository and never overwritten."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from pycardano import Network, PaymentSigningKey

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "generate_keys", REPO_ROOT / "scripts" / "generate_keys.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


keys = _load()


def test_keys_are_written_outside_the_repository(tmp_path):
    skey, vkey, address = keys.generate(tmp_path / "keys", "batcher")

    assert skey.exists() and vkey.exists()
    assert not keys.is_inside(skey, REPO_ROOT)
    assert address.network == Network.TESTNET
    assert str(address).startswith("addr_test1")
    assert PaymentSigningKey.load(str(skey)).to_verification_key().hash() == address.payment_part


def test_a_key_directory_inside_the_repository_is_refused():
    with pytest.raises(keys.UnsafeKeyLocation):
        keys.generate(REPO_ROOT / "keys-must-not-live-here", "batcher")
    assert not (REPO_ROOT / "keys-must-not-live-here").exists()


def test_an_existing_key_is_never_overwritten(tmp_path):
    keys.generate(tmp_path, "user")
    with pytest.raises(FileExistsError):
        keys.generate(tmp_path, "user")


def test_the_secret_scan_catches_a_generated_key(tmp_path):
    """P7-5's done-when: the pre-commit hook fires on a planted key."""
    spec = importlib.util.spec_from_file_location(
        "check_secrets", REPO_ROOT / "scripts" / "check_secrets.py"
    )
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)

    skey, _, _ = keys.generate(tmp_path, "batcher")
    assert scanner.scan_file(skey), "a real PyCardano .skey file slipped past the scan"
