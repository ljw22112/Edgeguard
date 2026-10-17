"""Learn the alert / speed policy on the many-to-many floor (sim/multi_sim.py) with the Cross-Entropy Method.

    python -m sim.train_multi --gens 6 --pop 10 --episodes 60          # results/train_multi.json

Policy = RiskConfig parameters that decide when to warn, how fast a truck may pass a waiting worker, how long an
alert holds, when GO is safe.  Physical limits (r_safe, the horizon) are not learned.

Score of a candidate on the training episodes (common random numbers: every candidate of a generation sees the
same episodes; half of them with workers who ignore 15 % of the alerts):
    throughput - 0.01 * worker seconds lost per episode - 0.5 * collisions per episode - 0.05 * close passes (< 1.5 m)
A collision costs as much as 50 % of an episode's whole forklift output, a close pass 5 %.

Training seeds are 10_000+ (round 2: 20_000+); candidates are picked on validation seeds 3_000+ and the comparison
with site practice tests on seeds 5_000+ (sim/site_compare.py --offset 5000), so the policy is judged on episodes it
never saw.
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
from sim.multi_sim import run_episode                                         # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOUNDS = {
    "t_warn": (2.5, 5.0), "t_danger": (1.0, 2.5), "m_warn": (0.0, 0.8), "worker_react": (0.5, 1.4),
    "brake_decel": (1.5, 3.0), "brake_margin": (0.4, 1.8), "lane_lookahead": (3.0, 8.0), "pass_speed": (0.8, 2.2),
    "clear_hold": (1.0, 3.0), "pass_speed_far": (1.5, 3.0), "pass_margin": (0.5, 2.0), "wait_lateral": (1.8, 3.2),
    "walk_speed": (1.0, 1.6), "env_lateral": (1.5, 3.2), "env_react": (0.4, 1.0),
}
# --mode priority: the worker yields, the truck keeps its speed inside its stopping envelope and brakes for
# stop points on its own (truck_priority, env_v2, stop_point, prompt_ease in edgeguard/alerting.py)
BOUNDS_PRIORITY = {
    "t_warn": (3.5, 5.0), "t_danger": (1.0, 2.0), "clear_hold": (1.0, 2.5), "worker_react": (0.5, 1.2),
    "brake_decel": (1.8, 2.8), "env_react": (0.3, 1.0), "env_lateral": (2.0, 4.0), "env_detect": (0.3, 1.2),
    "env_margin": (0.0, 0.8), "env_pass_floor": (1.2, 2.8), "walk_speed": (1.0, 1.6), "pass_speed": (1.2, 2.6),
    "pass_speed_far": (1.6, 3.0), "wait_lateral": (1.8, 3.0), "aside_margin": (0.3, 1.2),
    "comply_grace": (0.8, 2.5), "env_held_floor": (1.4, 3.0), "env_held_gap": (0.3, 1.5),
}
BOUNDS_PRIORITY["env_margin"] = (0.25, 0.8)          # covers position noise of a standing worker (audit)
FIXED = {"default": {"env_cap": True},
         "priority": {"env_cap": True, "truck_priority": True, "env_v2": True, "stop_point": True, "prompt_ease": True,
                      "aside_check_others": True}}
MODE = "default"
NAMES = list(BOUNDS)
LO = np.array([BOUNDS[n][0] for n in NAMES])
HI = np.array([BOUNDS[n][1] for n in NAMES])
W_WORKER, W_COLL, W_NEAR = 0.01, 0.5, 0.05


def set_mode(mode, w_coll=None):
    global MODE, BOUNDS, NAMES, LO, HI, W_COLL
    MODE = mode
    if w_coll is not None:
        W_COLL = w_coll
    if mode == "priority":
        BOUNDS = BOUNDS_PRIORITY
    NAMES = list(BOUNDS)
    LO = np.array([BOUNDS[n][0] for n in NAMES])
    HI = np.array([BOUNDS[n][1] for n in NAMES])


def to_over(z):
    over = {n: float(round(v, 3)) for n, v in zip(NAMES, LO + np.clip(z, 0, 1) * (HI - LO))}
    over.update(FIXED[MODE])                                # the stopping envelope is part of the learned policy
    return over


def job(a):
    seeds, over = a
    return [run_episode(s, 8, 4, comply=(1.0 if i % 2 == 0 else 0.85), over=over) for i, s in seeds]


def evaluate(pool, over, seeds, n):
    res = sum(pool.map(job, [([(i, s) for i, s in enumerate(seeds)][k::n], over) for k in range(n)]), [])
    ep = len(res)
    tot = {k: sum(r[k] for r in res) for k in ("collisions", "near", "forklift_m", "forklift_nominal_m", "worker_wait_s")}
    thr = tot["forklift_m"] / tot["forklift_nominal_m"]
    wl = tot["worker_wait_s"] / (ep * 8)
    score = thr - W_WORKER * wl - W_COLL * tot["collisions"] / ep - W_NEAR * tot["near"] / ep
    return {"score": round(score, 5), "throughput": round(thr, 4), "worker_lost_s": round(wl, 3),
            "collisions": tot["collisions"], "near": tot["near"], "episodes": ep}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=6)
    ap.add_argument("--pop", type=int, default=10)
    ap.add_argument("--elite", type=int, default=3)
    ap.add_argument("--episodes", type=int, default=60)
    ap.add_argument("--out", default="results/train_multi.json")
    ap.add_argument("--init", help="start from this JSON policy file (e.g. a previous run's best) instead of site.yaml")
    ap.add_argument("--seed-base", type=int, default=10_000, help="training seeds start here (never the evaluation seeds)")
    ap.add_argument("--mode", choices=sorted(FIXED), default="default")
    ap.add_argument("--w-coll", type=float, help="collision penalty per collision per episode (default 0.5)")
    ap.add_argument("--start", help="JSON overrides for the start policy (on top of site.yaml)")
    a = ap.parse_args()
    set_mode(a.mode, a.w_coll)
    from sim.failsafe_eval import site_cfg
    base = site_cfg()
    start = {k: getattr(base, k) for k in BOUNDS}
    if a.start:
        start.update({k: v for k, v in json.loads(a.start).items() if k in BOUNDS})
    if a.init:
        d = json.load(open(a.init))
        start.update({k: v for k, v in (d["history"][-1]["best_policy"] if "history" in d else d).items() if k in BOUNDS})
    z0 = np.array([(min(max(start[k], lo), hi) - lo) / (hi - lo) for k, (lo, hi) in BOUNDS.items()])
    print("start policy:", to_over(z0), flush=True)
    mu, sigma = z0.copy(), np.full(len(NAMES), 0.12 if a.init else 0.18)
    rng = np.random.default_rng(1)
    n = os.cpu_count() or 1
    hist = []
    with Pool(n) as pool:
        t0 = time.time()
        for g in range(a.gens):
            seeds = [random.Random(a.seed_base + 1000 * g + i).randrange(1 << 30) for i in range(a.episodes)]
            zs = [mu.copy()] + [np.clip(mu + sigma * rng.standard_normal(len(NAMES)), 0, 1) for _ in range(a.pop - 1)]
            if g == 0:
                zs[0] = z0.copy()                                 # the current site policy as a reference
            scored = []
            for z in zs:
                r = evaluate(pool, to_over(z), seeds, n)
                scored.append((r["score"], z, r))
            scored.sort(key=lambda x: -x[0])
            elite = np.array([z for _, z, _ in scored[:a.elite]])
            mu = 0.7 * elite.mean(axis=0) + 0.3 * mu
            sigma = np.maximum(0.04, 0.7 * elite.std(axis=0) + 0.3 * sigma)
            best = scored[0]
            ref = next(r for s_, z, r in scored if np.allclose(z, zs[0]))
            hist.append({"gen": g, "best": best[2], "best_policy": to_over(best[1]), "mean_policy": to_over(mu),
                         "generation_reference": ref, "secs": round(time.time() - t0)})
            print(f"gen {g}: best {best[2]}  (reference {ref['score']}, thr {ref['throughput']}, coll {ref['collisions']}, "
                  f"near {ref['near']})  {round(time.time() - t0)} s", flush=True)
            json.dump({"mode": a.mode, "bounds": BOUNDS, "weights": [W_WORKER, W_COLL, W_NEAR], "history": hist,
                       "final_mean": to_over(mu)}, open(os.path.join(ROOT, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
