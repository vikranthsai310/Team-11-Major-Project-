"""P0-8 — the pre-commit secret scan blocks key-shaped strings (NFR-6)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_scanner():
    spec = importlib.util.spec_from_file_location(
        "check_secrets", REPO_ROOT / "scripts" / "check_secrets.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scanner = _load_scanner()


# Built by concatenation so this test file does not itself contain a scannable
# key — otherwise committing the test would trip the hook it is testing.
PLANTED = {
    "signing key": "key = " + "ed25519_sk" + "q" * 40,
    "testnet address": "addr = " + "addr_test1" + "v" * 45,
    "blockfrost id": "BLOCKFROST_PROJECT_ID" + "=" + "preprod" + "A1b2C3d4" * 4,
    "seed phrase": " ".join(["abandon"] * 11 + ["about"]),
    # P7-5: the JSON text envelope PyCardano and cardano-cli write for .skey files.
    "key envelope": '"cborHex": "58' + "20" + "ab" * 32 + '"',
    "key type tag": '"type": "PaymentSigningKey' + 'Shelley_ed25519"',
}


PROSE_THAT_MUST_NOT_TRIP_THE_SCAN = (
    "The geometry shows the long title and the three roll numbers would wrap "
    "into two lines and could touch the rows beside them."
)


@pytest.mark.parametrize("label,content", sorted(PLANTED.items()))
def test_planted_key_shapes_are_blocked(tmp_path, label, content):
    path = tmp_path / "planted.py"
    path.write_text(content + "\n", encoding="utf-8")
    assert scanner.scan_file(path), f"{label} was not detected"
    assert scanner.main([str(path)]) == 1


def test_clean_file_passes(tmp_path):
    path = tmp_path / "clean.py"
    path.write_text("D_MAX = 120\nN_MIN = 8\n", encoding="utf-8")
    assert scanner.scan_file(path) == []
    assert scanner.main([str(path)]) == 0


def test_ordinary_prose_is_not_mistaken_for_a_seed_phrase(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text(PROSE_THAT_MUST_NOT_TRIP_THE_SCAN + "\n", encoding="utf-8")
    assert scanner.scan_file(path) == []


def test_allowlist_marker_silences_a_false_positive(tmp_path):
    path = tmp_path / "doc.py"
    path.write_text(
        "EXAMPLE = " + "'addr_test1" + "v" * 45 + "'  # " + scanner.ALLOWLIST_MARKER + "\n",
        encoding="utf-8",
    )
    assert scanner.scan_file(path) == []


def test_repository_is_clean(repo_root):
    """The scan the hook runs, applied to every tracked source file."""
    targets = [
        path
        for pattern in ("*.py", "*.toml", "*.yaml", "*.yml", "*.md", "*.cfg", "*.example")
        for path in repo_root.rglob(pattern)
        if ".venv" not in path.parts and ".git" not in path.parts
    ]
    findings = [f for path in targets for f in scanner.scan_file(path)]
    assert not findings, "\n".join(findings)
