"""The off-chain code reads exactly the scripts the Aiken compiler produced."""

from __future__ import annotations

import pytest
from pycardano import VerificationKeyHash

from batcher.onchain import blueprint

pytestmark = pytest.mark.skipif(
    not blueprint.BLUEPRINT.exists(), reason="onchain/plutus.json not built"
)


def test_python_computes_the_script_hash_the_compiler_recorded():
    """A mismatch would mean every script address the batcher derives is wrong."""
    compiled = blueprint.load()
    for title in ("order.order.spend", "pool.pool.spend"):
        validator = blueprint.validator(compiled, title)
        assert validator.hash.payload.hex() == validator.recorded_hash


def test_an_unknown_validator_is_a_loud_error():
    with pytest.raises(KeyError):
        blueprint.validator(blueprint.load(), "swap.nothing.spend")


def test_bytes_parameters_are_encoded_as_cbor_byte_strings():
    assert blueprint.parameter_cbor(b"\x01\x02") == "420102"


@pytest.mark.skipif(blueprint.aiken_executable() is None, reason="Aiken not installed")
def test_applying_parameters_yields_a_distinct_fully_applied_script():
    batcher = VerificationKeyHash(b"\xb0" * 28)
    unapplied = blueprint.validator(blueprint.load(), "pool.pool.spend")
    applied = blueprint.apply_parameters("pool", "pool", [batcher.payload])

    assert applied.hash != unapplied.hash
    assert applied.hash.payload.hex() == applied.recorded_hash
    # Deterministic: the same key always gives the same pool address.
    again = blueprint.apply_parameters("pool", "pool", [batcher.payload])
    assert again.hash == applied.hash
