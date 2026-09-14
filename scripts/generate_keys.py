"""P7-5 · Generate preprod keys **outside** the repository.

    python scripts/generate_keys.py --name batcher
    python scripts/generate_keys.py --name user        # a demo wallet that places orders

Writes ``<name>.skey`` and ``<name>.vkey`` into ``BATCHER_KEY_DIR`` (default
``~/.cardano-batcher``) and prints the preprod address to fund from the faucet.

Refuses to write anywhere inside the repository, and refuses to overwrite an
existing key: silently replacing a funded key would strand its test ADA. These are
testnet keys only; the settings guard makes mainnet unreachable (NFR-7).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pycardano import Address, Network, PaymentSigningKey, PaymentVerificationKey

from batcher.config.settings import load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


class UnsafeKeyLocation(RuntimeError):
    """The requested key directory is inside the repository."""


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def generate(key_dir: Path, name: str, repo_root: Path = REPO_ROOT) -> tuple[Path, Path, Address]:
    if is_inside(key_dir, repo_root):
        raise UnsafeKeyLocation(
            f"{key_dir} is inside the repository; keys belong in ~/.cardano-batcher/"
        )
    skey_path, vkey_path = key_dir / f"{name}.skey", key_dir / f"{name}.vkey"
    if skey_path.exists() or vkey_path.exists():
        raise FileExistsError(f"{skey_path} already exists; refusing to overwrite a key")

    key_dir.mkdir(parents=True, exist_ok=True)
    signing = PaymentSigningKey.generate()
    verification = PaymentVerificationKey.from_signing_key(signing)
    signing.save(str(skey_path))
    verification.save(str(vkey_path))

    address = Address(verification.hash(), network=Network.TESTNET)
    return skey_path, vkey_path, address


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="batcher", choices=["batcher", "user"])
    parser.add_argument("--key-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = load_settings()  # raises unless the network is preprod
    key_dir = args.key_dir or settings.batcher_key_dir
    skey, vkey, address = generate(key_dir, args.name)

    print(f"wrote {skey}")
    print(f"wrote {vkey}")
    print(f"\npreprod address ({args.name}): {address}")
    print("Fund it with test ADA from the Cardano testnet faucet (preprod).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
