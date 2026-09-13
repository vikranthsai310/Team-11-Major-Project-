"""Run manifests. A result without a manifest is not a result (docs/02 §9).

Every entry point calls :func:`write_manifest` so that any number reaching the
report can be traced back to the seed, the code, the configuration and the
dataset that produced it (NFR-3).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from batcher.config import params, protocol

EXPERIMENTS_ROOT = Path("experiments")


def module_values(module: ModuleType) -> dict[str, Any]:
    """Public constants of a config module, as a JSON-serialisable mapping."""
    return {
        name: getattr(module, name)
        for name in sorted(dir(module))
        if name.isupper() and not name.startswith("_")
    }


def config_hash() -> str:
    """Stable digest of the protocol parameters and project tunables in force."""
    payload = json.dumps(
        {"protocol": module_values(protocol), "params": module_values(params)},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def git_state() -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return out.stdout.strip()

    status = run("status", "--porcelain")
    return {"sha": run("rev-parse", "HEAD"), "dirty": bool(status) if status is not None else None}


def write_manifest(
    experiment_id: str,
    *,
    seed: int,
    dataset_checksum: str | None = None,
    root: Path = EXPERIMENTS_ROOT,
    **extra: Any,
) -> Path:
    """Write ``<root>/<experiment_id>/manifest.json`` and return its path.

    ``extra`` carries whatever the run needs to be reproducible that is not
    common to every run — tuned baseline values, reward weights, model
    checkpoints, CLI arguments.
    """
    manifest = {
        "experiment_id": experiment_id,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": seed,
        "git": git_state(),
        "config_hash": config_hash(),
        "dataset_checksum": dataset_checksum,
        "protocol": module_values(protocol),
        "params": module_values(params),
        **extra,
    }

    out_dir = root / experiment_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n")
    return path
