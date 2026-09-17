"""P8 · Robustness of the runtime shields — on the VALIDATION split only.

    python scripts/robustness_eval.py --data data/processed/d1_*.parquet \
        --models experiments/phase3-forecaster/models --episodes 10

Compares, on identical paired validation episodes at the matched and heavy rates:

* P2 (N=4)                      vs  DeadlineAwarePolicy(P2)
* P3 DQN seed 3 (as recorded)   vs  the same agent with only the opt-in mask repair
                                    (``illegal_action="largest"``)
                                vs  ShieldedPolicy(DQN, fallback=P2)

The test split is never opened: it was used once, by Phase 6. Every number here is
new and none of it feeds the Phase 6 tables. Missing inputs (the gitignored D1
dataset or DQN checkpoint) skip that part and say so rather than failing.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from batcher.config.params import ACTION_BUCKETS, D_MAX, DEFAULT_SEED, FORECAST_HORIZON
from batcher.config.protocol import MAX_BLOCK_EX_MEM
from batcher.eval import metrics
from batcher.policy.base import Action, Observation
from batcher.policy.optimizer import ConstrainedOptimizer
from batcher.policy.shield import DeadlineAwarePolicy, ShieldedPolicy
from batcher.sim.gym_env import WAIT_ACTION, BatchingEnv, _block_usage, _Row

EXPERIMENT = "phase8-robustness"
SPLIT = "val"  # never "test"
RATES = ("matched", "heavy")
DQN_CHECKPOINT = Path("experiments") / "phase5-dqn-seed3" / "models" / "dqn.zip"
REPORTED = (
    "l_p95",
    "l_p95_all",
    "w_max",
    "submit_wait_max",
    "overshoot",
    "late_share",
    "x_rate",
    "c_user",
    "interventions",
)


# --- per-episode summaries -----------------------------------------------------------


def summarise(result, submit_waits: list[int], interventions: int | None) -> dict:
    """The project's metrics plus the deadline view the audit asked for."""
    row = metrics.compute(result).as_dict()
    latencies = [order.latency for order in result.settled]
    submit_wait_max = max(submit_waits) if submit_waits else None
    row.update(
        submit_wait_max=submit_wait_max,
        # How far past D_MAX the oldest order already was when its batch went out.
        overshoot=max(0, submit_wait_max - D_MAX) if submit_wait_max is not None else None,
        # Settled orders whose arrival-to-confirmation latency exceeded D_MAX.
        late_share=float(np.mean([lat > D_MAX for lat in latencies])) if latencies else None,
        interventions=interventions,
    )
    return row


def simulator_run(policy, blocks, episode, process, forecaster, rate) -> dict:
    from batcher.sim.env import run_episode

    if hasattr(policy, "reset"):
        policy.reset()
    result = run_episode(
        blocks,
        policy,
        episode.stream(process, rate),
        episode.rng(),
        forecaster=forecaster,
        episode_id=episode.episode_id,
        policy_name=policy.name,
    )
    if not metrics.conserved(result):
        raise AssertionError(f"conservation failed: {policy.name} {episode.episode_id}")
    waits = [d["oldest_wait"] for d in result.decisions if d["action"] == "SUBMIT"]
    interventions = getattr(policy, "deadline_submissions", None)
    return summarise(result, waits, interventions)


# --- the DQN through the Gym env -----------------------------------------------------


def env_observation(env: BatchingEnv) -> Observation:
    """What a simulator policy would see at the env's current decision point."""
    block = env.blocks.iloc[env.index]
    slot = int(block["abs_slot"])
    sizes, mems, steps = env.queue.dimensions()
    _, block_mem, block_steps = _block_usage(_Row(block))
    return Observation(
        slot=slot,
        queue_depth=len(env.queue),
        oldest_wait=env.queue.oldest_wait(slot),
        queue_sizes=sizes,
        queue_mem=mems,
        queue_steps=steps,
        fill_hat=tuple(env._forecast(block)),
        mem_headroom=MAX_BLOCK_EX_MEM - block_mem,
        step_headroom=0,
        pool_locked=False,
        slots_in_flight=0,
        gate_a_max_n=env._gate_a_max(),
    )


def action_index(env: BatchingEnv, action: Action) -> int:
    """Map a simulator Action onto the env's discrete actions without exceeding it.

    The Gate A maximum has its own action; any other n becomes the largest bucket
    not above it (the env cannot express an arbitrary n).
    """
    if not action.submit or action.n == 0:
        return WAIT_ACTION
    ceiling = env._gate_a_max()
    if action.n >= ceiling:
        return len(ACTION_BUCKETS) + 1
    below = [i for i, n in enumerate(ACTION_BUCKETS, start=1) if n <= action.n]
    return below[-1] if below else 1


def greedy_action(model, state: np.ndarray) -> int:
    """``model.predict(state, deterministic=True)`` without SB3's per-call overhead.

    The same Q-network and the same argmax; asserted equal on the first episode.
    """
    import torch

    with torch.no_grad():
        q_values = model.q_net(torch.as_tensor(state, dtype=torch.float32)[None, :])
    return int(q_values.argmax(dim=1)[0])


class AgentPolicy:
    """The DQN as a Policy: it reads the env's own state vector, unchanged."""

    name = "p3(dqn)"

    def __init__(self, model, env: BatchingEnv):
        self.model = model
        self.env = env
        self.last_index = WAIT_ACTION

    def decide(self, obs: Observation) -> Action:
        self.last_index = greedy_action(self.model, self.env._state())
        return Action(
            submit=self.last_index != WAIT_ACTION, n=self.env._action_to_n(self.last_index)
        )

    def observe_outcome(self, outcome) -> None:
        return None


def dqn_run(model, blocks, episode, process, forecaster, rate, variant, check=False) -> dict:
    from batcher.sim.orders import ARRIVAL_RATES

    env = BatchingEnv(
        blocks,
        process,
        forecaster=forecaster,
        rate_multiplier=ARRIVAL_RATES[rate],
        seed=episode.seed,
        illegal_action="largest" if variant == "repair" else "first",
    )
    obs, _ = env.reset(seed=episode.seed)
    agent = AgentPolicy(model, env)
    shield = ShieldedPolicy(agent, fallback=ConstrainedOptimizer(n_min=4))
    submit_waits: list[int] = []

    terminated = False
    while not terminated:
        oldest = env.queue.oldest_wait(env.current_slot)
        if variant == "shield":
            before = shield.interventions
            decision = shield.decide(env_observation(env))
            # When the agent decided, execute its raw action so the shielded run
            # differs from the recorded one only where the shield intervened.
            index = agent.last_index if shield.interventions == before else None
            index = action_index(env, decision) if index is None else index
        else:
            index = greedy_action(model, obs)
            if check:
                assert index == int(model.predict(obs, deterministic=True)[0])
        submitted = len(env.submissions)
        obs, _, terminated, _, _ = env.step(int(index))
        if len(env.submissions) > submitted:
            submit_waits.append(oldest)

    result = env.to_episode_result()
    if not metrics.conserved(result):
        raise AssertionError(f"conservation failed: dqn/{variant} {episode.episode_id}")
    return summarise(result, submit_waits, shield.interventions if variant == "shield" else None)


# --- aggregation and output ----------------------------------------------------------


def aggregate(rows: pd.DataFrame) -> list[dict]:
    out = []
    for (rate, policy), group in rows.groupby(["rate", "policy"], sort=False):
        record = {"rate": rate, "policy": policy, "episodes": int(len(group))}
        for key in REPORTED:
            values = pd.to_numeric(group[key], errors="coerce").dropna()
            record[f"{key}_median"] = float(values.median()) if len(values) else None
        record["x_rate_max"] = float(group["x_rate"].max())
        record["overshoot_max"] = float(pd.to_numeric(group["overshoot"]).max())
        record["interventions_total"] = (
            int(pd.to_numeric(group["interventions"]).sum())
            if group["interventions"].notna().any()
            else None
        )
        record["gate_a_violations"] = int(group["gate_a_violations"].sum())
        out.append(record)
    return out


def fmt(value, digits=1) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "–"
    return f"{value:,.{digits}f}"


def markdown(summary: list[dict], notes: list[str], forecaster_label: str, episodes: int) -> str:
    lines = [
        "# Phase 8 · Robustness of the runtime shields (validation split)",
        "",
        f"{episodes} paired validation episodes per rate; medians across episodes. "
        f"Forecaster: {forecaster_label}. `l_p95_all` counts each expired order's wait "
        "until expiry (a lower bound). `overshoot` = oldest wait at submission minus "
        f"D_MAX={D_MAX}, per-episode maximum. `late` = share of settled orders with "
        "latency > D_MAX. Cost is lovelace per user.",
        "",
        "| rate | policy | L-p95 | L-p95 all | submit wait max | overshoot "
        "(med / max) | late | X-rate (med / max) | C-user | interventions (med / total) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summary:
        lines.append(
            f"| {r['rate']} | {r['policy']} | {fmt(r['l_p95_median'])} | "
            f"{fmt(r['l_p95_all_median'])} | {fmt(r['submit_wait_max_median'], 0)} | "
            f"{fmt(r['overshoot_median'], 0)} / {fmt(r['overshoot_max'], 0)} | "
            f"{fmt(r['late_share_median'], 3)} | "
            f"{fmt(r['x_rate_median'], 3)} / {fmt(r['x_rate_max'], 3)} | "
            f"{fmt(r['c_user_median'], 0)} | "
            f"{fmt(r['interventions_median'], 0)} / {fmt(r['interventions_total'], 0)} |"
        )
    lines += ["", "## Notes", "", *[f"- {note}" for note in notes], ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--models", type=Path, default=Path("experiments/phase3-forecaster/models"))
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--rates", nargs="+", default=list(RATES))
    parser.add_argument("--out", default=EXPERIMENT)
    args = parser.parse_args(argv)

    from batcher.data.collector import sha256_of
    from batcher.data.features import build_features, chronological_split, preprocess
    from batcher.forecast.base import CachedForecaster
    from batcher.forecast.lgbm import load as lgbm_load
    from batcher.sim.episodes import build_episodes
    from batcher.sim.orders import fit_arrival_process

    data = args.data or next(iter(sorted(Path("data/processed").glob("d1_blocks_*.parquet"))), None)
    if data is None or not Path(data).exists():
        print("D1 dataset not found under data/processed/; nothing to measure (skipped).")
        return 1

    notes = [
        f"Split: `{SPLIT}` (the test split is not opened). Episode set: build_episodes(seed="
        f"{DEFAULT_SEED}), the same construction Phase 6 used, on validation.",
        "P2 runs through the simulator (rollbacks modelled); DQN variants run through the "
        "Gym env, as Phase 6 did (no rollbacks). Compare within a family.",
        "DeadlineAwarePolicy: p90 of observed block gaps + p90 of observed confirmation "
        "delays, learned online per episode (priors 46 + 46 slots before 20 samples). "
        "Its `interventions` are deadline-pressure submissions.",
    ]

    started = time.perf_counter()
    frame = build_features(preprocess(pd.read_parquet(data)))
    process = fit_arrival_process(frame)
    episodes = build_episodes(
        frame, chronological_split(frame), which=SPLIT, count=args.episodes, seed=DEFAULT_SEED
    )
    forecaster = lgbm_load(args.models, horizon=FORECAST_HORIZON)
    label = getattr(forecaster, "label", forecaster.name)
    if getattr(forecaster, "is_fallback", False):
        notes.append(f"LightGBM unavailable: every forecast here is the {label}.")

    model = None
    if DQN_CHECKPOINT.exists():
        from stable_baselines3 import DQN

        model = DQN.load(DQN_CHECKPOINT)
    else:
        notes.append(f"DQN checkpoint {DQN_CHECKPOINT} not found locally: DQN part skipped.")

    print(f"{len(episodes)} {SPLIT} episodes x {args.rates} · forecaster {label}")
    rows, timings = [], {}
    print(f"  setup {time.perf_counter() - started:.0f} s", flush=True)
    for index, episode in enumerate(episodes):
        blocks = episode.blocks(frame)
        for rate in args.rates:
            runs = [
                ("p2(N=4)", simulator_run, ConstrainedOptimizer(n_min=4)),
                (
                    "deadline(p2(N=4))",
                    simulator_run,
                    DeadlineAwarePolicy(ConstrainedOptimizer(n_min=4)),
                ),
            ]
            if model is not None:
                runs += [
                    ("p3(dqn seed3)", dqn_run, "recorded"),
                    ("p3(dqn seed3)+largest-repair", dqn_run, "repair"),
                    ("shield(p3(dqn seed3), p2(N=4))", dqn_run, "shield"),
                ]
            prepared = CachedForecaster(forecaster, on_missing="conservative").prepare(blocks)
            for name, run, subject in runs:
                tick = time.perf_counter()
                if run is simulator_run:
                    row = simulator_run(subject, blocks, episode, process, prepared, rate)
                else:
                    row = dqn_run(
                        model, blocks, episode, process, prepared, rate, subject, check=index == 0
                    )
                timings[name] = timings.get(name, 0.0) + time.perf_counter() - tick
                rows.append({"policy": name, "rate": rate, "episode_id": episode.episode_id} | row)
        elapsed = time.perf_counter() - started
        print(f"  episode {index + 1}/{len(episodes)}  ({elapsed:.0f} s)", flush=True)
    print("  seconds per policy:", {k: round(v, 1) for k, v in timings.items()})

    table = pd.DataFrame(rows)
    summary = aggregate(table)

    out_dir = Path("experiments") / args.out
    manifest = None
    try:
        from batcher.eval.manifest import write_manifest

        manifest = write_manifest(
            args.out,
            seed=DEFAULT_SEED,
            dataset_checksum=sha256_of(Path(data)),
            split=SPLIT,
            episodes=len(episodes),
            rates=list(args.rates),
            forecaster=label,
            dqn_checkpoint=str(DQN_CHECKPOINT) if model is not None else None,
            runtime_seconds=round(time.perf_counter() - started, 1),
        )
    except Exception as error:  # the results stand without it; say so
        notes.append(f"manifest not written: {type(error).__name__}: {error}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(
            {"split": SPLIT, "episodes": len(episodes), "forecaster": label, "summary": summary},
            indent=2,
            default=str,
        )
        + "\n"
    )
    table.to_csv(out_dir / "episode_metrics.csv", index=False)
    (out_dir / "results.md").write_text(
        markdown(summary, notes, label, len(episodes)), encoding="utf-8"
    )
    print(markdown(summary, notes, label, len(episodes)).encode("ascii", "replace").decode())
    if manifest:
        print(f"manifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
