"""Capacity calibration: live protocol limits and learned estimate corrections.

The live batcher's Gate A must stay safe when governance tightens a limit and
when real transactions are larger than the estimator models. Everything here is
pure: protocol parameters and measurements are plain objects.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pycardano.exception import InvalidTransactionException

from batcher.build import calibration
from batcher.build.calibration import (
    CONFIGURED_LIMITS,
    MEM,
    MIN_FACTOR,
    MIN_SAMPLES,
    SAFETY_MARGIN,
    SIZE,
    STEPS,
    CapacityCalibrator,
    capacity_failure,
    read_d4_rows,
)
from batcher.build.estimator import (
    ORDER_MEM,
    ORDER_SIZE_B,
    ORDER_STEPS,
    max_n_satisfying_gate_a,
    tx_mem,
    tx_size,
    tx_steps,
)
from batcher.config.protocol import (
    MAX_TX_EX_MEM,
    MAX_TX_EX_STEPS,
    MAX_TX_SIZE,
    MIN_FEE_A,
    MIN_FEE_B,
    PRICE_MEM,
    PRICE_STEPS,
)

QUEUE = 60
SIZES, MEMS, STEPS_ = [ORDER_SIZE_B] * QUEUE, [ORDER_MEM] * QUEUE, [ORDER_STEPS] * QUEUE

# The one real preprod row: n = 1.
D4_ROW = {
    "n": 1,
    "est_size": 800,
    "actual_size": 2682,
    "est_mem": 2_500_000,
    "actual_mem": 473_756,
    "est_steps": 1_000_000_000,
    "actual_steps": 166_037_580,
    "outcome": "included",
}


def params(**overrides):
    values = {
        "max_tx_size": MAX_TX_SIZE,
        "max_tx_ex_mem": MAX_TX_EX_MEM,
        "max_tx_ex_steps": MAX_TX_EX_STEPS,
        "min_fee_coefficient": MIN_FEE_A,
        "min_fee_constant": MIN_FEE_B,
        "price_mem": PRICE_MEM,
        "price_step": PRICE_STEPS,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def max_n(cal: CapacityCalibrator) -> int:
    return cal.max_n(SIZES, MEMS, STEPS_)


def test_with_no_evidence_the_calibrated_gate_is_the_static_gate():
    assert max_n(CapacityCalibrator()) == max_n_satisfying_gate_a(SIZES, MEMS, STEPS_)


# --- live protocol limits -----------------------------------------------------------------


def test_a_stricter_live_limit_lowers_gate_a_and_warns():
    cal = CapacityCalibrator()
    before = max_n(cal)
    cal.apply_protocol_params(params(max_tx_ex_mem=MAX_TX_EX_MEM // 2), height=7)

    assert cal.limits.mem == MAX_TX_EX_MEM // 2
    assert max_n(cal) < before
    (warning,) = cal.warnings
    assert "protocol parameter changed" in warning["message"] and warning["height"] == 7
    assert cal.snapshot()["warnings"] == [warning["message"]]
    assert cal.snapshot()["warnings"] == [], "a warning is reported once"


def test_an_unchanged_stricter_limit_is_not_warned_about_again():
    cal = CapacityCalibrator()
    cal.apply_protocol_params(params(max_tx_size=8_000))
    cal.apply_protocol_params(params(max_tx_size=8_000))
    assert len(cal.warnings) == 1


def test_a_looser_live_limit_does_not_raise_gate_a_above_the_constant():
    cal = CapacityCalibrator()
    before = max_n(cal)
    cal.apply_protocol_params(
        params(
            max_tx_size=MAX_TX_SIZE * 4,
            max_tx_ex_mem=MAX_TX_EX_MEM * 4,
            max_tx_ex_steps=MAX_TX_EX_STEPS * 4,
        )
    )
    assert cal.limits == CONFIGURED_LIMITS
    assert max_n(cal) == before
    assert cal.warnings == []
    assert cal.live_limits[SIZE] == MAX_TX_SIZE * 4, "the live value stays observable"


def test_missing_or_nonsense_live_values_fall_back_to_the_constant():
    cal = CapacityCalibrator()
    cal.apply_protocol_params(SimpleNamespace(max_tx_size=None, max_tx_ex_mem=0))
    assert cal.limits == CONFIGURED_LIMITS


def test_a_changed_fee_parameter_is_warned_about_once():
    cal = CapacityCalibrator()
    cal.apply_protocol_params(params(min_fee_coefficient=MIN_FEE_A + 1))
    cal.apply_protocol_params(params(min_fee_coefficient=MIN_FEE_A + 1))
    (warning,) = cal.warnings
    assert "fee parameter changed" in warning["message"]


class Context:
    def __init__(self, epoch=1, fail=False):
        self.epoch = epoch
        self.fail = fail
        self.reads = 0
        self.max_tx_size = MAX_TX_SIZE

    @property
    def protocol_param(self):
        self.reads += 1
        if self.fail:
            raise ConnectionError("down")
        return params(max_tx_size=self.max_tx_size)


def test_limits_are_refreshed_every_n_blocks_or_on_a_new_epoch_not_every_block():
    context = Context()
    cal = CapacityCalibrator(refresh_blocks=10)
    assert cal.refresh(context, 100)
    assert not cal.refresh(context, 105)
    assert cal.refresh(context, 110)
    context.epoch = 2
    context.max_tx_size = 9_000
    assert cal.refresh(context, 111), "a new epoch is read at once"
    assert cal.limits.size == 9_000 and context.reads == 3


def test_an_unreadable_refresh_keeps_the_limits_and_retries():
    context = Context()
    cal = CapacityCalibrator(refresh_blocks=10)
    context.max_tx_size = 9_000
    cal.refresh(context, 100)
    context.fail = True
    assert not cal.refresh(context, 110)
    assert cal.limits.size == 9_000
    assert any("unreadable" in w["message"] for w in cal.warnings)
    context.fail = False
    assert cal.refresh(context, 111), "a failed read is retried at the next call"


# --- learned corrections ------------------------------------------------------------------


def test_a_transaction_3_4x_larger_than_estimated_raises_the_size_factor_at_once():
    cal = CapacityCalibrator()
    before = max_n(cal)
    cal.observe(SIZE, 800, 2_720)

    assert cal.factors[SIZE] == pytest.approx(3.4 * (1 + SAFETY_MARGIN))
    after = max_n(cal)
    assert after < before
    size, _, _ = cal.corrected(after, SIZES, MEMS, STEPS_)
    assert size <= MAX_TX_SIZE
    assert cal.corrected(after + 1, SIZES, MEMS, STEPS_)[0] > MAX_TX_SIZE


def test_a_factor_below_one_needs_min_samples_consistent_observations():
    cal = CapacityCalibrator()
    for _ in range(MIN_SAMPLES - 1):
        cal.observe(MEM, 2_500_000, 1_500_000)  # ratio 0.6
    assert cal.factors[MEM] == 1.0, "too little evidence to trust a lower estimate"

    cal.observe(MEM, 2_500_000, 1_500_000)
    assert cal.factors[MEM] == pytest.approx(0.6 * (1 + SAFETY_MARGIN))


def test_one_high_observation_restarts_the_evidence_for_a_lower_factor():
    cal = CapacityCalibrator()
    for _ in range(MIN_SAMPLES - 1):
        cal.observe(STEPS, 1_000, 600)
    cal.observe(STEPS, 1_000, 1_000)  # at the estimate: argues for no reduction
    for _ in range(MIN_SAMPLES - 1):
        cal.observe(STEPS, 1_000, 600)
    assert cal.factors[STEPS] >= 1.0


def test_a_lower_factor_never_goes_below_the_floor():
    cal = CapacityCalibrator()
    for _ in range(MIN_SAMPLES * 4):
        cal.observe(MEM, 2_500_000, 100_000)  # ratio 0.04
    assert cal.factors[MEM] == MIN_FACTOR


def test_a_lower_factor_is_no_lower_than_the_largest_recent_ratio_allows():
    cal = CapacityCalibrator()
    for actual in (500, 700, 500, 500, 500):
        cal.observe(STEPS, 1_000, actual)
    assert cal.factors[STEPS] >= 0.7 * (1 + SAFETY_MARGIN)


def test_a_repeated_measurement_key_is_learned_from_once():
    cal = CapacityCalibrator()
    for _ in range(MIN_SAMPLES):
        cal.observe_measurement((1_000, 1_000, 1_000), (1_000, 500, 500), key="same batch")
    assert cal.corrections[MEM].samples == 1


def test_seeding_from_d4_rows(tmp_path):
    path = tmp_path / "d4.jsonl"
    path.write_text(json.dumps(D4_ROW) + "\nnot json\n" + json.dumps({"n": 2}) + "\n")
    cal = CapacityCalibrator()

    assert cal.seed_from_d4(read_d4_rows(path)) == 1
    assert cal.factors[SIZE] == pytest.approx(2682 / 800 * (1 + SAFETY_MARGIN))
    assert cal.factors[MEM] == 1.0 and cal.factors[STEPS] == 1.0, "one row cannot lower them"
    assert max_n(cal) < max_n_satisfying_gate_a(SIZES, MEMS, STEPS_)
    assert read_d4_rows(tmp_path / "missing.jsonl") == []


# --- failures -----------------------------------------------------------------------------


def test_pycardano_size_refusals_are_recognised_with_their_measured_size():
    error = InvalidTransactionException(
        "Transaction size (20000) exceeds the max limit (16384). Please try reducing"
    )
    assert capacity_failure(error) == ((SIZE,), 20_000)


@pytest.mark.parametrize(
    ("message", "dimensions"),
    [
        ("ShelleyTxValidationError MaxTxSizeUTxO 17000 16384", (SIZE,)),
        ("ExUnitsTooBigUTxO (ExUnits {exUnitsMem = 1, exUnitsSteps = 2})", (MEM, STEPS)),
        ("evaluation: the budget was overspent (cpu)", (STEPS,)),
        ("execution units exceed the maximum memory", (MEM,)),
    ],
)
def test_ledger_and_evaluator_refusals_are_recognised(message, dimensions):
    assert capacity_failure(RuntimeError(message))[0] == dimensions


def test_unrelated_failures_are_not_capacity_failures():
    assert capacity_failure(RuntimeError("EvaluationFailure")) is None
    assert capacity_failure(RuntimeError("UTxOSelectionException: not enough funds")) is None


def test_a_size_refusal_teaches_the_measured_ratio():
    cal = CapacityCalibrator()
    error = InvalidTransactionException("Transaction size (22000) exceeds the max limit (16384)")
    sizes = SIZES[:20]
    assert cal.record_failure(error, sizes, MEMS[:20], STEPS_[:20]) == (SIZE,)
    assert cal.factors[SIZE] == pytest.approx(22_000 / tx_size(20, sizes) * (1 + SAFETY_MARGIN))
    assert max_n(cal) < 20


def test_a_budget_refusal_tightens_what_it_names_at_least_to_the_limit_bound():
    cal = CapacityCalibrator()
    n = 10
    assert cal.record_failure(
        RuntimeError("ExUnitsTooBigUTxO memory"), SIZES[:n], MEMS[:n], STEPS_[:n]
    ) == (MEM,)
    bound = MAX_TX_EX_MEM / tx_mem(n, MEMS[:n])
    assert cal.factors[MEM] >= bound * (1 + SAFETY_MARGIN)
    assert cal.factors[MEM] >= calibration.FAILURE_TIGHTEN
    assert cal.factors[STEPS] == 1.0 and cal.factors[SIZE] == 1.0
    assert not cal.fits(n, SIZES, MEMS, STEPS_), "the refused n no longer passes Gate A"


def test_a_non_capacity_failure_teaches_nothing():
    cal = CapacityCalibrator()
    assert cal.record_failure(RuntimeError("boom"), SIZES[:3], MEMS[:3], STEPS_[:3]) == ()
    assert cal.factors == {SIZE: 1.0, MEM: 1.0, STEPS: 1.0}


def test_exceeded_compares_measurements_with_the_effective_limits():
    cal = CapacityCalibrator()
    cal.apply_protocol_params(params(max_tx_size=2_000))
    built = SimpleNamespace(actual_size=2_682, actual_mem=473_756, actual_steps=tx_steps(1))
    assert cal.exceeded(built) == [SIZE]


def test_the_snapshot_exposes_factors_limits_and_samples():
    cal = CapacityCalibrator()
    cal.seed_from_d4([D4_ROW])
    snap = cal.snapshot()
    assert snap["limits"] == {"size": MAX_TX_SIZE, "mem": MAX_TX_EX_MEM, "steps": MAX_TX_EX_STEPS}
    assert snap["factors"][SIZE] > 3 and snap["samples"] == {SIZE: 1, MEM: 1, STEPS: 1}
    json.dumps(snap)  # records are JSON lines


def test_corrected_estimates_reuse_the_estimator():
    cal = CapacityCalibrator()
    assert cal.corrected(5, SIZES, MEMS, STEPS_) == (
        tx_size(5, SIZES),
        tx_mem(5, MEMS),
        tx_steps(5, STEPS_),
    )
