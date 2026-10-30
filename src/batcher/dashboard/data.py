"""Everything the dashboard shows, computed by the project's own code (P7-12).

The dashboard never produces a result (``docs/17-UI-SPEC.md`` §A1). Each view reads
something that already exists:

* **Run** replays one of the 100 paired *test* episodes through ``run_episode`` —
  the simulator that produced the reported numbers — and returns its D3 decision
  log, so what plays on screen is exactly what the evaluation measured.
* **Compare** reads the one-shot test evaluation in
  ``experiments/phase6-final-evaluation``: medians with bootstrap CIs, the latency
  distribution, never a re-run.
* **Live** reads the deployed DEX on preprod through Blockfrost, plus the recorded
  transactions of the first end-to-end swap.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from batcher.build.estimator import block_usage_from_fill, max_n_satisfying_gate_b
from batcher.config.params import D_MAX, DEFAULT_SEED, FORECAST_HORIZON, TTL_SLOTS
from batcher.dashboard.live import (  # noqa: F401 - re-exported for callers of data
    DEMO_MANIFEST,
    EXPLORER,
    LiveSource,
    live_payload,
    recorded_transactions,
)
from batcher.eval import metrics
from batcher.eval.stats import median_ci

REPO = Path(__file__).resolve().parents[3]
EVALUATION = REPO / "experiments" / "phase6-final-evaluation"

POLICY_LABELS = {
    "null": "NULL · deadline only",
    "e1(M=16)": "E1 · fixed size, M = 16",
    "e2(T=20)": "E2 · fixed interval, T = 20",
    "e3(greedy)": "E3 · greedy",
    "p2(D=120,N=1)": "P2 · optimizer, N = 1 (≡ greedy)",
    "p2(D=120,N=4)": "P2 · optimizer, N = 4",
    "p3(dqn)": "P3 · DQN agent, 5 seeds",
    "oracle(D=120,N=4)": "ORACLE · perfect forecast",
}
POLICY_ORDER = list(POLICY_LABELS)
TABLE_METRICS = ["l_mean", "l_p95", "c_user", "x_rate", "throughput", "f_jain"]
RATES = ["light", "matched", "heavy"]
ROW_COLUMNS = [
    "slot",
    "height",
    "fill",
    "forecast",
    "depth",
    "oldest",
    "locked",
    "submit",
    "n",
    "gate_a",
    "gate_b",
    "resolution",
]


class NotReady(RuntimeError):
    """The episode library is still loading the dataset."""


def clean(value):
    """Strict JSON: NaN and infinities become null; numpy scalars become Python."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# --- Run view ---------------------------------------------------------------------------


def forecast_series(blocks: pd.DataFrame, forecaster) -> dict[int, float]:
    """Next-block forecast for every block, as the policy would have seen it."""
    predictions = np.clip(forecaster.predict_frame(blocks)[:, 0], 0.0, 1.0)
    return {int(s): float(p) for s, p in zip(blocks["abs_slot"], predictions, strict=True)}


def forecaster_label(forecaster) -> str:
    """What actually produced the forecast — never "lgbm" when E4 stood in for it."""
    if forecaster is None:
        return "none"
    return str(getattr(forecaster, "label", None) or forecaster.name)


def gate_b_max(fill_hat: float | None, gate_a: int | None) -> int | None:
    """Largest batch predicted to fit the next block, never above the Gate A cap."""
    if fill_hat is None or gate_a is None:
        return None
    if gate_a <= 0:
        return 0
    return max_n_satisfying_gate_b(*block_usage_from_fill(fill_hat), limit=gate_a)


def episode_payload(
    blocks: pd.DataFrame,
    result,
    forecast: dict[int, float],
    *,
    policy_key: str,
    policy_label: str,
    episode_id: str,
    rate: str,
    d_max: int = D_MAX,
) -> dict:
    heights = (
        dict(zip(blocks["abs_slot"].astype(int), blocks["block_height"].astype(int), strict=True))
        if "block_height" in blocks
        else {}
    )
    rows = []
    for decision in result.decisions:
        slot = int(decision["abs_slot"])
        gate_a = decision.get("gate_a_max_n")
        gate_a = None if gate_a is None or pd.isna(gate_a) else int(gate_a)
        submitting = decision["action"] == "SUBMIT"
        rows.append(
            [
                slot,
                heights.get(slot),
                round(float(decision["fill_actual"]), 4),
                None if slot not in forecast else round(forecast[slot], 4),
                int(decision["queue_depth"]),
                int(decision["oldest_wait"]),
                1 if decision["pool_locked"] else 0,
                1 if submitting else 0,
                int(decision["n"]) if submitting else 0,
                gate_a,
                gate_b_max(forecast.get(slot), gate_a),
                decision.get("resolution"),
            ]
        )

    return clean(
        {
            "episode_id": episode_id,
            "policy": policy_key,
            "policy_label": policy_label,
            "rate": rate,
            "d_max": d_max,
            "ttl_slots": TTL_SLOTS,
            "start_slot": int(blocks["abs_slot"].iloc[0]),
            "end_slot": int(blocks["abs_slot"].iloc[-1]),
            "columns": ROW_COLUMNS,
            "rows": rows,
            "settled": sorted(
                ([o.arrival_slot, o.confirm_slot] for o in result.settled), key=lambda p: p[1]
            ),
            "expired": sorted(int(o.ttl_slot) for o in result.expired),
            "metrics": metrics.compute(result).as_dict(),
        }
    )


REPLAY_POLICIES: dict[str, tuple[str, str]] = {
    "p2": ("P2 · optimizer, N = 4", "lgbm"),
    "e3": ("E3 · greedy", "lgbm"),
    "e2": ("E2 · fixed interval, T = 20", "lgbm"),
    "e1": ("E1 · fixed size, M = 16", "lgbm"),
    "oracle": ("ORACLE · perfect forecast", "oracle"),
}


def make_policy(key: str):
    from batcher.policy.optimizer import ConstrainedOptimizer, OracleOptimizer
    from batcher.policy.static import FixedInterval, FixedSize, Greedy

    factories = {
        "p2": lambda: ConstrainedOptimizer(n_min=4),
        "e3": Greedy,
        "e2": lambda: FixedInterval(t=20),
        "e1": lambda: FixedSize(m=16),
        "oracle": lambda: OracleOptimizer(n_min=4),
    }
    return factories[key]()


class EpisodeLibrary:
    """The test episodes of the final evaluation, loaded once in the background."""

    def __init__(self, data_path: Path | None, models: Path, count: int = 100):
        self.data_path = data_path
        self.models = models
        self.count = count
        self.state = "idle"
        self.message = ""
        self.forecaster = ""
        self._cache: dict[tuple, dict] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self.load, name="episode-library", daemon=True).start()

    def load(self) -> None:  # pragma: no cover - needs the gitignored 92-day dataset
        try:
            from batcher.data.features import build_features, chronological_split, preprocess
            from batcher.forecast.baseline import Oracle
            from batcher.forecast.lgbm import load as lgbm_load
            from batcher.sim.episodes import build_episodes
            from batcher.sim.orders import fit_arrival_process

            if self.data_path is None or not self.data_path.exists():
                raise FileNotFoundError("the D1 dataset is not in data/processed/")
            self.state, self.message = "loading", "Reading 388,781 blocks and building features…"
            frame = build_features(preprocess(pd.read_parquet(self.data_path)))
            self.message = "Fitting the order arrival process…"
            self.process = fit_arrival_process(frame)
            self.episodes = build_episodes(
                frame, chronological_split(frame), which="test", count=self.count, seed=DEFAULT_SEED
            )
            self.message = "Loading the trained forecaster…"
            self.forecasters = {
                "lgbm": lgbm_load(self.models, horizon=FORECAST_HORIZON),
                "oracle": Oracle(horizon=FORECAST_HORIZON),
            }
            self.forecaster = forecaster_label(self.forecasters["lgbm"])
            self.frame = frame
            self.congested = [
                float((e.blocks(frame)["fill_pct"] > 0.80).mean()) for e in self.episodes
            ]
            self.state, self.message = "ready", ""
        except Exception as error:  # surfaced in the UI rather than crashing the server
            self.state, self.message = "error", f"{type(error).__name__}: {error}"

    def catalogue(self) -> dict:
        episodes = []
        if self.state == "ready":
            episodes = [
                {"index": i, "id": e.episode_id, "congested": self.congested[i]}
                for i, e in enumerate(self.episodes)
            ]
        return {
            "state": self.state,
            "message": self.message,
            "forecaster": self.forecaster,
            "policies": [{"key": k, "label": v[0]} for k, v in REPLAY_POLICIES.items()],
            "rates": RATES,
            "episodes": episodes,
        }

    def replay(self, policy: str, rate: str, index: int) -> dict:  # pragma: no cover
        if self.state != "ready":
            raise NotReady(self.message or self.state)
        if policy not in REPLAY_POLICIES or rate not in RATES:
            raise KeyError(f"unknown policy or rate: {policy}, {rate}")
        if not 0 <= index < len(self.episodes):
            raise KeyError(f"episode index out of range: {index}")

        key = (policy, rate, index)
        with self._lock:
            if key in self._cache:
                return self._cache[key]

        from batcher.forecast.base import CachedForecaster
        from batcher.sim.env import run_episode

        episode = self.episodes[index]
        blocks = episode.blocks(self.frame)
        label, kind = REPLAY_POLICIES[policy]
        forecaster = self.forecasters[kind]
        result = run_episode(
            blocks,
            make_policy(policy),
            episode.stream(self.process, rate),
            episode.rng(),
            forecaster=CachedForecaster(forecaster).prepare(blocks),
            episode_id=episode.episode_id,
            policy_name=policy,
        )
        payload = episode_payload(
            blocks,
            result,
            forecast_series(blocks, forecaster),
            policy_key=policy,
            policy_label=label,
            episode_id=episode.episode_id,
            rate=rate,
        )
        payload["congested"] = self.congested[index]
        payload["forecaster"] = forecaster_label(forecaster)
        with self._lock:
            self._cache[key] = payload
        return payload


# --- Compare view ---------------------------------------------------------------------------


def compare_payload(experiment: Path = EVALUATION) -> dict:
    """The test-split results, exactly as the report tables compute them."""
    results = pd.read_parquet(experiment / "episode_metrics.parquet")
    manifest = json.loads((experiment / "manifest.json").read_text())
    family = results.groupby("policy")["family"].first().to_dict()

    numeric = [c for c in results.columns if results[c].dtype.kind in "fiu" and c != "seed"]
    per_episode = results.groupby(["policy", "rate", "episode_id"], as_index=False)[numeric].mean()

    rates = {}
    for rate in RATES:
        subset = per_episode[per_episode["rate"] == rate]
        rows = []
        for key in POLICY_ORDER:
            group = subset[subset["policy"] == key]
            if group.empty:
                continue
            cells = {m: list(median_ci(group[m].to_numpy())) for m in TABLE_METRICS}
            rows.append(
                {"key": key, "label": POLICY_LABELS[key], "family": family.get(key), **cells}
            )
        rates[rate] = rows

    latencies = pd.read_parquet(experiment / "latencies.parquet")
    percentiles = np.linspace(0, 100, 101)
    cdf = {
        key: np.percentile(group["latency"].to_numpy(), percentiles).round(1).tolist()
        for key, group in latencies.groupby("policy")
    }
    return clean(
        {
            "split": manifest.get("split"),
            "episodes": manifest.get("episodes"),
            "p3_seeds": manifest.get("p3_seeds"),
            "gate_a_violations": manifest.get("gate_a_violations"),
            "labels": POLICY_LABELS,
            "rates": rates,
            "cdf_matched": cdf,
        }
    )
