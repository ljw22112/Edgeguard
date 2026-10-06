"""Train the alert / speed-command policy with a reward function, select it with an
evaluation function that balances accident prediction against throughput.

    python -m sim.train_policy --penalties 5 20 50 100 --iters 10

Policy = the tunable parameters of the risk engine and alert policy (RiskConfig).
Optimiser = Cross-Entropy Method (gradient-free policy search, common in RL for
small parameter vectors), with common random numbers inside an iteration.

Reward (per encounter, maximised during training):
    r = - C * collision  - forklift_seconds_lost  - 0.5 * false_alarm
    C = collision penalty in "seconds of forklift time" - swept, because it sets
        how much productivity we are willing to trade for safety.

Evaluation (on held-out encounters, used to pick C and the final policy):
    F_beta with beta = 2 (recall = warned >= 1 s before a real conflict, weighted 2x)
    throughput = forklift distance driven / distance with no slow-downs
    score = F_beta * throughput / throughput_default
    Safety comes first: only policies whose collisions are within 10 % (+1) of the
    safest candidate are eligible; among those the highest score wins.

Domain randomisation: every training encounter draws its own UWB noise
(0.1-0.35 m), network latency (40-220 ms), uplink loss (0-20 %) and alert
loss (0-10 %), so the policy does not overfit one network condition.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import random
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard.risk import RiskConfig                        # noqa: E402
from sim import scenarios                                    # noqa: E402
from sim.closed_loop import Net, run_episode, score          # noqa: E402

GENS = scenarios.GENERATORS + scenarios.EXTRA_GENERATORS
BOUNDS = {                                  # name: (low, high)
    "t_warn": (2.0, 4.5), "t_danger": (0.8, 2.5), "m_warn": (0.0, 1.0),
    "worker_react": (0.3, 1.5), "brake_decel": (1.0, 3.0), "brake_margin": (0.2, 2.0),
    "lane_lookahead": (2.0, 10.0), "pass_speed": (0.3, 2.5), "clear_hold": (0.5, 3.5),
    "stand_speed": (0.2, 0.9),
}
NAMES = list(BOUNDS)
LO = np.array([BOUNDS[n][0] for n in NAMES])
HI = np.array([BOUNDS[n][1] for n in NAMES])


def to_cfg(z):
    v = LO + np.clip(z, 0, 1) * (HI - LO)
    p = {n: float(round(x, 3)) for n, x in zip(NAMES, v)}
    p["t_danger"] = min(p["t_danger"], p["t_warn"] - 0.2)
    return RiskConfig(**p), p


def from_cfg(cfg):
    return np.array([(getattr(cfg, n) - BOUNDS[n][0]) / (BOUNDS[n][1] - BOUNDS[n][0]) for n in NAMES])


def episodes_for(seed, per_gen, randomize=True):
    """Deterministic list of (gen index, episode seed, noise, net) - common random numbers."""
    rng = random.Random(seed)
    out = []
    for gi in range(len(GENS)):
        for _ in range(per_gen):
            if randomize:
                net = Net(latency_ms=rng.uniform(40, 220), jitter_ms=rng.uniform(5, 40),
                          up_loss=rng.uniform(0, 0.2), down_loss=rng.uniform(0, 0.1))
                noise = rng.uniform(0.1, 0.35)
            else:
                net, noise = Net(), 0.15
            out.append((gi, rng.randrange(1 << 30), noise, net))
    return out


METHOD = "guidance_ctrv"                        # predictor used inside the loop (--method)


def _evaluate(args):
    z, eps, method = args
    cfg, _ = to_cfg(z)
    return [run_episode(GENS[gi], random.Random(s), cfg, method=method, net=net, noise=noise)
            for gi, s, noise, net in eps]


def evaluate(pool, zs, eps, chunks=2):
    """Evaluate several parameter vectors on the same encounters (split across processes)."""
    jobs = []
    for z in zs:
        for c in range(chunks):
            jobs.append((z, eps[c::chunks], METHOD))
    out = pool.map(_evaluate, jobs)
    res = []
    for i in range(len(zs)):
        merged = []
        for c in range(chunks):
            merged += out[i * chunks + c]
        res.append(merged)
    return res


def cem(pool, penalty, iters, pop, per_gen, seed, log, w_fp=0.5):
    rng = np.random.default_rng(seed)
    mu, sd = from_cfg(RiskConfig()), np.full(len(NAMES), 0.22)
    best = (-1e9, mu.copy())
    for it in range(iters):
        eps = episodes_for(seed * 1000 + it, per_gen)
        zs = [mu.copy()] + [np.clip(mu + sd * rng.standard_normal(len(NAMES)), 0, 1) for _ in range(pop - 1)]
        batch = evaluate(pool, zs, eps)
        scores = [score(b, collision_penalty=penalty, w_fp=w_fp) for b in batch]
        rewards = np.array([s["reward"] for s in scores])
        elite = np.argsort(rewards)[-max(2, pop // 4):]
        mu = 0.3 * mu + 0.7 * np.mean([zs[i] for i in elite], axis=0)
        sd = np.maximum(0.3 * sd + 0.7 * np.std([zs[i] for i in elite], axis=0), 0.03)
        i_best = int(np.argmax(rewards))
        if rewards[i_best] > best[0]:
            best = (float(rewards[i_best]), zs[i_best].copy())
        s0 = scores[0]
        log.append({"penalty": penalty, "w_fp": w_fp, "iter": it, "reward_mean_policy": s0["reward"],
                    "reward_best": float(rewards[i_best]), "collisions_mean_policy": s0["collisions"],
                    "throughput_mean_policy": s0["throughput"], "f_beta_mean_policy": s0["f_beta"]})
        print(f"  C={penalty:5.0f} it {it:2d}  reward {s0['reward']:7.2f} (best {rewards[i_best]:7.2f})  "
              f"coll {s0['collisions']:2d}/{s0['conflicts']}  thr {s0['throughput']:.3f}  "
              f"F2 {s0['f_beta']:.3f}", flush=True)
    return mu, best[1]


def select(rows):
    """Safety first (near-minimum collisions), then F_beta x relative throughput."""
    thr0 = rows[0]["throughput"]
    safest = min(r["collisions"] for r in rows)
    for r in rows:
        r["eligible"] = r["collisions"] <= safest * 1.1 + 1
        r["score"] = round(r["f_beta"] * r["throughput"] / thr0, 4) if r["eligible"] else None
    return max((r for r in rows if r["score"] is not None), key=lambda r: r["score"])


def write_policy(chosen, root):
    with open(os.path.join(root, "config", "policy_trained.yaml"), "w") as fh:
        fh.write(f"# Trained alert policy ({chosen['policy']}), from sim/train_policy.py\n"
                 "# Merge into the `risk:` section of your site config to use it.\n")
        fh.write("risk:\n")
        for k, v in chosen["params"].items():
            fh.write(f"  {k}: {v}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--penalties", type=float, nargs="+", default=[5, 20, 50, 100])
    ap.add_argument("--w-fp", type=float, nargs="+", default=[0.5],
                    help="false-alarm penalties to train with (one run per C x w_fp)")
    ap.add_argument("--extra-policy", nargs="*", default=[],
                    help="name=path.yaml policies to include in validation (e.g. a previous run)")
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--pop", type=int, default=14)
    ap.add_argument("--per-gen", type=int, default=8, help="training encounters per scenario type")
    ap.add_argument("--val-per-gen", type=int, default=30)
    ap.add_argument("--beta", type=float, default=2.0)
    ap.add_argument("--out", default="results/policy_training.json")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--method", default="guidance_ctrv", help="guidance_ctrv | guidance_lstm")
    ap.add_argument("--no-write", action="store_true", help="do not overwrite config/policy_trained.yaml")
    a = ap.parse_args()
    global METHOD
    METHOD = a.method

    t0 = time.time()
    log, cands = [], {}
    val_eps = episodes_for(999_999, a.val_per_gen)                    # held out, randomised conditions
    with Pool(max(1, os.cpu_count() or 1)) as pool:
        default_z = from_cfg(RiskConfig())
        for C in a.penalties:
            for wfp in a.w_fp:
                tag = f"C={C:g}" + ("" if wfp == 0.5 else f",fp={wfp:g}")
                print(f"training {tag}", flush=True)
                mu, best = cem(pool, C, a.iters, a.pop, a.per_gen, a.seed, log, w_fp=wfp)
                cands[tag] = mu
        import yaml
        for spec in a.extra_policy:
            name, path = spec.split("=", 1)
            cands[name] = from_cfg(RiskConfig(**{k: v for k, v in yaml.safe_load(open(path))["risk"].items()
                                                if k in NAMES}))
        names = ["default"] + list(cands)
        zs = [default_z] + [cands[n] for n in names[1:]]
        val = evaluate(pool, zs, val_eps)
    rows = []
    for n, z, res in zip(names, zs, val):
        s = score(res, beta=a.beta)
        s1 = score(res, beta=1.0)
        s3 = score(res, beta=3.0)
        _, params = to_cfg(z)
        rows.append({"policy": n, "params": params, **{k: s[k] for k in
                     ("precision", "recall", "f_beta", "throughput", "collisions", "conflicts",
                      "episodes", "false_alarms", "lost_s_mean")},
                     "f1": s1["f_beta"], "f3": s3["f_beta"]})
    chosen = select(rows)
    print("\nvalidation (held-out, randomised conditions)")
    print(f"{'policy':10s} {'coll':>5s} {'recall':>7s} {'prec':>6s} {'F2':>6s} {'thr':>6s} {'lost s':>7s} {'score':>6s}")
    for r in rows:
        sc = "-" if r["score"] is None else f"{r['score']:.3f}"
        print(f"{r['policy']:10s} {r['collisions']:3d}/{r['conflicts']:<3d} {r['recall']:7.3f} {r['precision']:6.3f} "
              f"{r['f_beta']:6.3f} {r['throughput']:6.3f} {r['lost_s_mean']:7.2f} {sc:>6s}")
    print("chosen:", chosen["policy"], chosen["params"])
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"validation": rows, "chosen": chosen["policy"], "training_log": log,
               "settings": {**vars(a), "minutes": round((time.time() - t0) / 60, 1),
                            "bounds": BOUNDS}}, open(a.out, "w"), indent=1)
    if not a.no_write:
        write_policy(chosen, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--reselect":       # re-apply selection to a saved run
        d = json.load(open(sys.argv[2]))
        ch = select(d["validation"])
        d["chosen"] = ch["policy"]
        json.dump(d, open(sys.argv[2], "w"), indent=1)
        write_policy(ch, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for r in d["validation"]:
            print(r["policy"], r["collisions"], round(r["throughput"], 3), round(r["f_beta"], 3), r["score"])
        print("chosen:", ch["policy"])
    else:
        main()
