"""Read the compiled validators from ``onchain/plutus.json`` and apply parameters.

Both validators are parameterised by the batcher's key hash (and the order
validator by the pool token), so their addresses exist only once the keys and the
token do. Parameters are applied with ``aiken blueprint apply`` — the compiler that
produced the code — rather than by editing UPLC in Python.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cbor2
from pycardano import PlutusData, PlutusV3Script, ScriptHash, plutus_script_hash

ONCHAIN = Path(__file__).resolve().parents[3] / "onchain"
BLUEPRINT = ONCHAIN / "plutus.json"


@dataclass(frozen=True)
class CompiledValidator:
    title: str
    script: PlutusV3Script
    recorded_hash: str

    @property
    def hash(self) -> ScriptHash:
        return plutus_script_hash(self.script)


def load(path: Path = BLUEPRINT) -> dict:
    return json.loads(Path(path).read_text())


def validator(blueprint: dict, title: str) -> CompiledValidator:
    """``title`` as the blueprint names it, e.g. ``order.order.spend``."""
    for entry in blueprint["validators"]:
        if entry["title"] == title:
            return CompiledValidator(
                title=title,
                script=PlutusV3Script(bytes.fromhex(entry["compiledCode"])),
                recorded_hash=entry["hash"],
            )
    raise KeyError(f"no validator titled {title!r} in the blueprint")


def parameter_cbor(value: bytes | PlutusData) -> str:
    """A validator parameter as hex CBOR, the form ``aiken blueprint apply`` takes."""
    if isinstance(value, PlutusData):
        return value.to_cbor_hex()
    return cbor2.dumps(bytes(value)).hex()


def aiken_executable() -> str | None:
    found = shutil.which("aiken")
    if found:
        return found
    candidate = Path(os.environ.get("USERPROFILE", Path.home())) / ".aiken" / "bin" / "aiken.exe"
    return str(candidate) if candidate.exists() else None


def apply_parameters(
    module: str,
    name: str,
    parameters: list[bytes | PlutusData],
    blueprint_path: Path = BLUEPRINT,
) -> CompiledValidator:
    """Apply ``parameters`` in order and return the fully applied spend validator."""
    aiken = aiken_executable()
    if aiken is None:
        raise RuntimeError("the Aiken compiler is not installed; see docs/13-RUNBOOK.md")

    with tempfile.TemporaryDirectory() as scratch:
        current = Path(blueprint_path)
        for step, value in enumerate(parameters):
            out = Path(scratch) / f"applied-{step}.json"
            subprocess.run(
                [
                    aiken,
                    "blueprint",
                    "apply",
                    "-i",
                    str(current),
                    "-o",
                    str(out),
                    "-m",
                    module,
                    "-v",
                    name,
                    parameter_cbor(value),
                ],
                cwd=ONCHAIN,
                check=True,
                capture_output=True,
            )
            current = out
        return validator(load(current), f"{module}.{name}.spend")
