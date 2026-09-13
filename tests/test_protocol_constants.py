"""T-C1 and T-C2 — the protocol constants and the single-source-of-truth guard."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from batcher.config import protocol

# Expected values, transcribed independently from docs/07-CONSTRAINTS-COST-MODEL.md §1.
# Deliberately duplicated here: a test that imported the value it is checking would
# pass no matter what the value became.
DOCUMENTED = {
    "MAX_TX_SIZE": 16_384,
    "MAX_TX_EX_MEM": 14_000_000,
    "MAX_TX_EX_STEPS": 10_000_000_000,
    "MAX_BLOCK_SIZE": 90_112,
    "MAX_BLOCK_EX_MEM": 62_000_000,
    "MAX_BLOCK_EX_STEPS": 40_000_000_000,
    "MIN_FEE_A": 44,
    "MIN_FEE_B": 155_381,
    "PRICE_MEM": 0.0577,
    "PRICE_STEPS": 0.0000721,
    "SLOT_SECONDS": 1,
    "ACTIVE_SLOT_COEFF": 0.05,
}

# T-C2: these may not appear as literals anywhere under src/ except protocol.py.
FORBIDDEN_LITERALS = {16384, 14000000, 10000000000, 90112, 62000000, 40000000000, 155381}

# MIN_FEE_A is small enough to occur innocently, so it is policed contextually:
# flagged only on a line that is talking about fees.
FEE_CONTEXT = re.compile(r"fee|lovelace", re.IGNORECASE)

_UNDERSCORE_IN_NUMBER = re.compile(r"(?<=\d)_(?=\d)")
_INTEGER = re.compile(r"\b\d+\b")


def find_protocol_literals(path: Path) -> list[str]:
    """Return a finding per line of ``path`` that hard-codes a protocol constant."""
    findings: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = _UNDERSCORE_IN_NUMBER.sub("", raw)
        values = {int(match) for match in _INTEGER.findall(line)}

        for value in sorted(values & FORBIDDEN_LITERALS):
            findings.append(f"{path}:{lineno}: protocol constant {value} hard-coded")

        if protocol.MIN_FEE_A in values and FEE_CONTEXT.search(line):
            findings.append(f"{path}:{lineno}: fee coefficient {protocol.MIN_FEE_A} hard-coded")
    return findings


def test_constants_match_the_specification():
    """T-C1 — every value matches docs/07-CONSTRAINTS-COST-MODEL.md §1 exactly."""
    actual = {name: getattr(protocol, name) for name in DOCUMENTED}
    assert actual == DOCUMENTED


def test_no_constant_literals_outside_protocol(src_root):
    """T-C2 — NFR-4: protocol values appear in exactly one module."""
    findings: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        if path.name == "protocol.py":
            continue
        findings.extend(find_protocol_literals(path))

    message = "Protocol constants must be imported from batcher.config.protocol:\n"
    assert not findings, message + "\n".join(findings)


def test_no_source_file_is_hidden_from_git(repo_root, src_root):
    """Every source file must be tracked, or the repository is not the project.

    `.gitignore` carried the conventional `build/` entry, which without a leading
    slash matches *any* directory of that name — including `src/batcher/build/`,
    the fee model and both capacity gates. The package was silently absent from
    every commit until CI could not import it. Tests passing locally say nothing
    about what was actually published.
    """
    sources = [
        path
        for directory in ("src", "tests", "scripts")
        for path in (repo_root / directory).rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    assert sources, "no source files found"

    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        input="\n".join(str(path) for path in sources),
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    ignored = [line for line in result.stdout.splitlines() if line.strip()]
    assert not ignored, "source files excluded by .gitignore:\n" + "\n".join(ignored)

    tracked = subprocess.run(
        ["git", "ls-files", str(src_root)], capture_output=True, text=True, cwd=repo_root
    ).stdout
    assert "batcher/build/estimator.py" in tracked.replace("\\", "/")


def test_the_no_literals_check_catches_a_planted_literal(tmp_path):
    """T-C2 must fail when it should: a deliberately planted literal is detected."""
    planted = tmp_path / "planted.py"
    planted.write_text("max_batch_bytes = 16_384\n", encoding="utf-8")
    assert find_protocol_literals(planted)

    fee_literal = tmp_path / "planted_fee.py"
    fee_literal.write_text("fee = 44 * size\n", encoding="utf-8")
    assert find_protocol_literals(fee_literal)

    innocent = tmp_path / "innocent.py"
    innocent.write_text("retries = 44\nwindow = 20\n", encoding="utf-8")
    assert not find_protocol_literals(innocent)
