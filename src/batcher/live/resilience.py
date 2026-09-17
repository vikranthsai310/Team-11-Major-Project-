"""The chain port made to survive its provider: retries, a circuit breaker, failover.

Blockfrost rate-limits, times out and has outages. Before this wrapper any of
those propagated out of ``LiveBatcher.run`` and stopped the daemon — possibly
with a batch in flight. :class:`ResilientChain` implements the same
:class:`~batcher.live.chain.LiveChain` port, so the daemon is unchanged by it:

* **Retries** with exponential backoff and jitter absorb a transient error.
* **A circuit breaker** per provider stops hammering one that keeps failing:
  after ``failure_threshold`` consecutive failed calls it opens for
  ``cooldown_seconds``, during which calls to it fail at once. The first call
  after the cool-down is a trial; success closes the breaker, failure reopens it.
* **Failover** tries secondary providers in order when the primary is exhausted
  or open.

When no provider can answer, :class:`ChainUnavailable` is raised. The daemon
treats it as "no view of the chain this poll": it decides nothing and submits
nothing (see ``LiveBatcher.step``).

**Submission is never retried or failed over.** A submit that timed out may
still have reached the mempool; sending it again is at best rejected and at worst
misreported. It goes once, to the first provider whose breaker is closed.

Every clock, sleep and random source is injectable, so all of it is tested
offline without waiting.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pycardano import Transaction, UTxO

from batcher.live.chain import LiveChain, Tip

DEFAULT_RETRIES = 3  # extra attempts per provider after the first
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 8.0
DEFAULT_JITTER = 0.5  # each delay is stretched by up to this fraction, at random
DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_COOLDOWN_SECONDS = 60.0


class ChainUnavailable(RuntimeError):
    """No chain provider could answer: all failed, or every breaker is open."""


def is_api_error(error: BaseException) -> bool:
    """Whether ``error`` means "the chain could not be read", not a defect.

    Covers :class:`ChainUnavailable`, network-level failures, and Blockfrost's
    ``ApiError`` (matched by name so the offline tests need no Blockfrost).
    """
    if isinstance(error, ChainUnavailable | ConnectionError | TimeoutError):
        return True
    kind = type(error)
    module = kind.__module__ or ""
    return kind.__name__ == "ApiError" or module.startswith(("requests", "urllib3", "blockfrost"))


def is_retryable(error: BaseException) -> bool:
    """Retry anything except a client error the provider will answer the same way.

    A 4xx other than 429 (rate limited) is a bad request, not an outage; it also
    proves the provider is reachable, so it does not count against the breaker.
    """
    status = getattr(error, "status_code", None)
    return not (isinstance(status, int) and 400 <= status < 500 and status != 429)


@dataclass
class CircuitBreaker:
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    clock: Callable[[], float] = time.monotonic
    failures: int = 0
    opened_at: float | None = field(default=None)

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.clock() - self.opened_at >= self.cooldown_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        # A failed trial after the cool-down reopens at once.
        if self.failures >= self.failure_threshold or self.opened_at is not None:
            self.opened_at = self.clock()


class ResilientChain:
    """A :class:`LiveChain` over one primary and any number of secondary providers."""

    def __init__(
        self,
        primary: LiveChain,
        secondaries: Sequence[LiveChain] = (),
        *,
        retries: int = DEFAULT_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
        max_delay: float = DEFAULT_MAX_DELAY_SECONDS,
        jitter: float = DEFAULT_JITTER,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
        retryable: Callable[[BaseException], bool] = is_retryable,
    ):
        self.providers: list[LiveChain] = [primary, *secondaries]
        # Transactions are built against the primary's context throughout.
        self.context = primary.context
        self.retries = retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.sleep = sleep
        self.rng = rng
        self.retryable = retryable
        self.breakers = [
            CircuitBreaker(failure_threshold, cooldown_seconds, clock) for _ in self.providers
        ]

    # --- the port ------------------------------------------------------------------------

    def tip(self) -> Tip:
        return self._call("tip")

    def recent_fills(self, count: int) -> list[float]:
        return self._call("recent_fills", count)

    def utxos(self, address) -> list[UTxO]:
        return self._call("utxos", address)

    def arrival_slot(self, tx_hash: str) -> int:
        return self._call("arrival_slot", tx_hash)

    def inclusion_slot(self, tx_hash: str) -> int | None:
        return self._call("inclusion_slot", tx_hash)

    def submit(self, tx: Transaction) -> str:
        for provider, breaker in zip(self.providers, self.breakers, strict=True):
            if not breaker.allow():
                continue
            try:
                tx_id = provider.submit(tx)
            except Exception as error:
                if is_api_error(error):
                    breaker.record_failure()
                raise  # once only: see the module docstring
            breaker.record_success()
            return tx_id
        raise ChainUnavailable("every chain provider's circuit breaker is open; not submitting")

    # --- the machinery -------------------------------------------------------------------

    def delay(self, attempt: int) -> float:
        """Backoff before retry ``attempt`` (0-based): doubling, capped, jittered."""
        base = min(self.max_delay, self.base_delay * 2**attempt)
        return base * (1 + self.jitter * self.rng())

    def _call(self, method: str, *args):
        last: BaseException | None = None
        for provider, breaker in zip(self.providers, self.breakers, strict=True):
            if not breaker.allow():
                continue
            for attempt in range(self.retries + 1):
                try:
                    result = getattr(provider, method)(*args)
                except Exception as error:
                    if not self.retryable(error):
                        breaker.record_success()  # reachable; the request is at fault
                        raise
                    last = error
                    breaker.record_failure()
                    if not breaker.allow() or attempt == self.retries:
                        break  # this provider is done; fail over
                    self.sleep(self.delay(attempt))
                    continue
                breaker.record_success()
                return result
        if last is None:
            raise ChainUnavailable(f"{method}: every chain provider's circuit breaker is open")
        raise ChainUnavailable(f"{method}: {type(last).__name__}: {last}") from last
