"""Phase 0 smoke check: is this environment able to produce a trustworthy number?

Loads the settings (which enforces the preprod guard), prints the protocol
parameters in force, and writes a run manifest — exercising the reproducibility
path end to end before any real experiment depends on it.

    python scripts/verify_setup.py
"""

from __future__ import annotations

from batcher.config import params, protocol
from batcher.config.settings import load_settings
from batcher.eval.manifest import config_hash, module_values, write_manifest


def main() -> int:
    settings = load_settings()

    print(f"network            {settings.cardano_network}")
    print(f"blockfrost key     {'set' if settings.blockfrost_project_id else 'not set'}")
    print(f"key directory      {settings.batcher_key_dir}")
    print(f"config hash        {config_hash()[:16]}")

    print("\nprotocol parameters")
    for name, value in module_values(protocol).items():
        print(f"  {name:<20} {value}")

    print("\nproject tunables")
    for name, value in module_values(params).items():
        print(f"  {name:<20} {value}")

    path = write_manifest("phase0-verify-setup", seed=params.DEFAULT_SEED)
    print(f"\nmanifest written   {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
