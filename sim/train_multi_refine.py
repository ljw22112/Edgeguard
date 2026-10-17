"""Train the alert / speed policy on the many-to-many floor (sim/multi_sim.py), where the site comparison runs.

    python -m sim.train_multi_refine --iters 6 --pop 12 --episodes 60

Policy = RiskConfig parameters below.  Optimiser = Cross-Entropy Method (gradient-free), common random
numbers within an iteration, fresh episodes every iteration.  Three disjoint seed sets:
  training    seeds from offset 1000 (a new block every iteration)
  selection   seeds from offset 3000: the top candidates are re-run and the final policy is picked here
  test        seeds from offset 200: the 300 episodes of sim/site_compare.py - never used for training or picking
Reward per candidate (seconds of forklift time as the unit):
  - 60 x collisions - 15 x close calls (< 1.5 m)  - forklift seconds lost - 0.5 x worker seconds lost - 0.02 x alarms
Safety first at selection: fewest (20 x collisions + close calls), then the highest throughput.
Output: results/train_multi_refine.json (history, chosen parameters, before/after on the selection set).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.failsafe_eval import site_cfg                                        # noqa: E402
from sim.multi_sim import run_episode                                         # noqa: E402

BOUNDS = {
    "t_warn": (2.0, 4.5), "t_danger": (0.8, 2.5), "m_warn": (0.0, 1.0), "worker_react": (0.3, 1.5),
    "brake_decel": (1.0, 3.0), "brake_margin": (0.2, 2.0), "lane_lookahead": (2.0, 10.0),
    "pass_speed": (0.5, 2.0), "pass_speed_far": (1.0, 3.0), "pass_margin": (0.3, 2.0), "clear_hold": (0.5, 3.5),
    "aside_margin": (0.3, 1.5), "aside_hold_speed": (0.0, 1.2), "wait_lateral": (1.5, 3.5),
}
NAMES = list(BOUNDS)
LO = np.array([BOUNDS[n][0] for n in NAMES])
HI = np.array([BOUNDS[n][1] for n in NAMES])
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def current():
    c = site_cfg()
    return {n: float(getattr(c, n)) for n in NAMES}


def to_params(z):
    v = LO + np.clip(z, 0, 1) * (HI - LO)
    return {n: round(float(x), 3) for n, x in zip(NAMES, v)}


def to_z(p):
    return (np.array([p[n] for n in NAMES]) - LO) / (HI - LO)


def job(a):
    seeds, over = a
    return [run_episode(s, 8, 4, over=over) for s in seeds]


def evaluate(pool, over, seeds, n):
    res = sum(pool.map(job, [(seeds[i::n], over) for i in range(n)]), [])
    t = {k: sum(r[k] for r in res) for k in res[0]}
    t["episodes"] = len(seeds)
    t["throughput"] = t["forklift_m"] / t["forklift_nominal_m"]
    t["reward"] = -(60 * t["collisions"] + 15 * t["close_calls"] + t["forklift_lost_s"] + 0.5 * t["worker_wait_s"]
                    + 0.02 * t["alarms"]) / len(seeds)
    return t


def seeds_at(offset, n):
    return [random.Random(7 + offset + i).randrange(1 << 30) for i in range(n)]


def brief(t):
    return {k: (round(t[k], 4) if isinstance(t[k], float) else t[k]) for k in
            ("collisions", "close_calls", "conflicts", "throughput", "forklift_lost_s", "worker_wait_s", "alarms", "reward")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=6)
    ap.add_argument("--pop", type=int, default=12)
    ap.add_argument("--elite", type=int, default=4)
    ap.add_argument("--episodes", type=int, default=60)
    ap.add_argument("--select-episodes", type=int, default=200)
    a = ap.parse_args()
    n = os.cpu_count() or 1
    rng = np.random.default_rng(20261017)
    base = current()
    mu, sd = to_z(base), np.full(len(NAMES), 0.15)
    hist, pool_cands = [], []
    t0 = time.time()
    with Pool(n) as pool:
        for it in range(a.iters):
            seeds = seeds_at(1000 + it * a.episodes, a.episodes)
            zs = [mu] + [mu + sd * rng.standard_normal(len(NAMES)) for _ in range(a.pop - 1)]
            scored = []
            for z in zs:
                p = to_params(z)
                t = evaluate(pool, p, seeds, n)
                scored.append((t["reward"], p, t))
            scored.sort(key=lambda x: -x[0])
            elite = [to_z(p) for _, p, _ in scored[:a.elite]]
            mu = np.mean(elite, axis=0)
            sd = np.maximum(np.std(elite, axis=0), 0.03)
            pool_cands += [(r, p) for r, p, _ in scored[:2]]
            hist.append({"iter": it, "best": brief(scored[0][2]), "mean_policy": brief(scored[0 if zs[0] is mu else 0][2]),
                         "best_params": scored[0][1]})
            print(f"iter {it}: best reward {scored[0][0]:.2f} (current policy {[s for s in scored if s[1] == to_params(zs[0])][0][0]:.2f}) "
                  f"coll {scored[0][2]['collisions']} close {scored[0][2]['close_calls']} thr {scored[0][2]['throughput']:.3f} "
                  f"[{time.time() - t0:.0f} s]", flush=True)
            json.dump({"history": hist}, open(os.path.join(ROOT, "results", "train_multi_refine.json"), "w"), indent=1)
        # selection on a separate seed set: current policy, final mean, best candidates
        sel = seeds_at(3000, a.select_episodes)
        cands = [("current", base), ("cem_mean", to_params(mu))] + \
                [(f"cand{i}", p) for i, (_, p) in enumerate(sorted(pool_cands, key=lambda x: -x[0])[:4])]
        rows = []
        for name, p in cands:
            t = evaluate(pool, p, sel, n)
            rows.append({"name": name, "params": p, **brief(t)})
            print(f"select {name:8s} coll {t['collisions']} close {t['close_calls']} thr {t['throughput']:.4f} "
                  f"alarms {t['alarms']} worker {t['worker_wait_s'] / (a.select_episodes * 8):.2f}", flush=True)
    cur = rows[0]
    safe = [r for r in rows if 20 * r["collisions"] + r["close_calls"] <= 20 * cur["collisions"] + cur["close_calls"]]
    best = max(safe, key=lambda r: r["throughput"])
    json.dump({"history": hist, "selection": rows, "chosen": best["name"], "chosen_params": best["params"],
               "current_params": base}, open(os.path.join(ROOT, "results", "train_multi_refine.json"), "w"), indent=1)
    print("chosen:", best["name"], json.dumps(best["params"]))


if __name__ == "__main__":
    main()
