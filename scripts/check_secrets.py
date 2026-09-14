"""Pre-commit secret scan (P0-8).

Greps staged files for key-shaped strings. Exits non-zero, naming the file and
line, if anything matches — so a signing key or an API token cannot reach the
repository by accident (NFR-6).

Bypassing this with ``git commit --no-verify`` is forbidden; see
``docs/13-RUNBOOK.md`` §8. A false positive is silenced by appending
``# pragma: allowlist secret`` to the offending line.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWLIST_MARKER = "pragma: allowlist secret"

# This file necessarily contains the patterns it looks for.
SELF = Path(__file__).name

PATTERNS: dict[str, re.Pattern[str]] = {
    "cardano signing key": re.compile(r"\b(?:ed25519e?_sk|xprv)[0-9a-z]{20,}"),
    # The text-envelope format cardano-cli and PyCardano write for .skey files:
    # a CBOR byte string of 32 (5820) or 64/96 (5840/5860) bytes of key material.
    "cardano key envelope": re.compile(r"\"cborHex\"\s*:\s*\"58(?:20|40|60)[0-9a-fA-F]{64,}"),
    "signing key type tag": re.compile(r"SigningKey\w*_ed25519"),
    "cardano address": re.compile(r"\b(?:addr|stake)(?:_test)?1[0-9a-z]{30,}"),
    "blockfrost project id": re.compile(r"\b(?:mainnet|preprod|preview)[0-9A-Za-z]{28,}"),
    "assigned blockfrost id": re.compile(r"BLOCKFROST_PROJECT_ID\s*=\s*[\"']?[0-9A-Za-z]{8,}"),
    "long base58 run": re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{80,}\b"),
    # A seed phrase is a bare line of 12-24 lowercase words with no punctuation.
    # Anchored, because an unanchored version matches ordinary English prose.
    "mnemonic-like phrase": re.compile(r"^\s*[\"']?(?:[a-z]{3,8} ){11,23}[a-z]{3,8}[\"']?[,]?\s*$"),
}

BINARY_SUFFIXES = {".parquet", ".png", ".pdf", ".pptx", ".docx", ".drawio", ".zip", ".pt"}


def scan_file(path: Path) -> list[str]:
    if path.name == SELF or path.suffix.lower() in BINARY_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOWLIST_MARKER in line:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(f"{path}:{lineno}: possible {label}")
    return findings


def main(argv: list[str]) -> int:
    findings = [f for arg in argv for f in scan_file(Path(arg))]
    if findings:
        print("Secret scan blocked this commit:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nMove the value into .env (gitignored) or ~/.cardano-batcher/. "
            "Do not commit with --no-verify.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
