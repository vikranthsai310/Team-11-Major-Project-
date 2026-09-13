"""Runtime settings and the preprod network guard (NFR-7).

Mainnet is unreachable **by construction**, not by discipline: a ``Settings``
object cannot exist unless the configured network is preprod, so every code path
that needs settings is gated, and there is no flag or override that relaxes it.
Enforced by T-C3.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ALLOWED_NETWORK = "preprod"

_DEFAULT_KEY_DIR = "~/.cardano-batcher"


class SettingsError(RuntimeError):
    """Raised when the environment is not a configuration this project may run in."""


@dataclass(frozen=True)
class Settings:
    cardano_network: str
    blockfrost_project_id: str | None
    batcher_key_dir: Path

    def __post_init__(self) -> None:
        # Validating in __post_init__ rather than in the loader means a Settings
        # instance is *unforgeable* for any network but preprod, however it is built.
        if self.cardano_network != ALLOWED_NETWORK:
            raise SettingsError(
                f"CARDANO_NETWORK is {self.cardano_network!r}; this project runs only "
                f"on {ALLOWED_NETWORK!r}. Mainnet is out of scope (PRD N5, NFR-7)."
            )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Load settings from a ``.env`` file and the process environment."""
    if env is None:
        _load_dotenv()
        env = os.environ

    return Settings(
        cardano_network=env.get("CARDANO_NETWORK", ALLOWED_NETWORK),
        blockfrost_project_id=env.get("BLOCKFROST_PROJECT_ID") or None,
        batcher_key_dir=Path(env.get("BATCHER_KEY_DIR", _DEFAULT_KEY_DIR)).expanduser(),
    )


def _load_dotenv() -> None:
    # Optional so that the unit suite runs in a minimal environment, before the
    # heavier ML dependencies have been installed.
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()
