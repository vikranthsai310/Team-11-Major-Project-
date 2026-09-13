"""The Policy interface — the thing that makes the comparison honest.

Every policy, static or learned, sees exactly this observation and returns
exactly this action. The simulator cannot tell them apart, so a difference in
results is a difference in decision logic and nothing else
(``docs/02-TECH-SPEC.md`` §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

OrderId = str


@dataclass(frozen=True)
class Observation:
    """Everything a policy is allowed to know at a decision point."""

    slot: int
    queue_depth: int
    oldest_wait: int
    queue_sizes: tuple[int, ...]
    queue_mem: tuple[int, ...]
    queue_steps: tuple[int, ...]
    fill_hat: tuple[float, ...]
    mem_headroom: int
    step_headroom: int
    pool_locked: bool
    slots_in_flight: int
    gate_a_max_n: int = 0


@dataclass(frozen=True)
class Action:
    submit: bool
    n: int = 0

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValueError("batch size cannot be negative")


WAIT = Action(submit=False)


@dataclass(frozen=True)
class Outcome:
    """What happened to a submitted batch.

    There is deliberately **no rejection-for-lateness state**. A submitted
    transaction is not bounced by a full block; it waits in the mempool until it
    is included or its validity interval passes (ADR-004). Adding a "bounce"
    member here would reintroduce the failure model that correction removed.
    """

    included: bool
    slots_to_confirm: int | None
    fee_lovelace: int
    n: int
    expired: list[OrderId] = field(default_factory=list)


@runtime_checkable
class Policy(Protocol):
    name: str

    def decide(self, obs: Observation) -> Action: ...

    def observe_outcome(self, outcome: Outcome) -> None: ...


class StatelessPolicy:
    """Base for policies that learn nothing from outcomes (E1, E2, E3, NULL)."""

    name = "stateless"

    def decide(self, obs: Observation) -> Action:  # pragma: no cover - abstract
        raise NotImplementedError

    def observe_outcome(self, outcome: Outcome) -> None:
        return None

    def reset(self) -> None:
        return None
