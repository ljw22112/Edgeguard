"""v0.9 cooperative D2D: how much does it depend on the peer-to-peer link?

    python -m sim.d2d_sensitivity --per-gen 30 --out results/d2d_sensitivity.json

Mode coop, conditions where D2D matters (dead zones, MEC down, network down); each case changes
the D2D broadcast: frame loss (crowded 2.4 GHz, interference) and range (metal racks).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard.device_policy import ForkliftLimit                   # noqa: E402
from sim.closed_loop import run_episode, score                      # noqa: E402
from sim.failsafe_eval import condition, site_cfg                   # noqa: E402
from sim.train_policy import GENS, episodes_for                     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONDS = ("forklift_dead_zone_8s", "worker_dead_zone_8s", "mec_dead_8s", "network_down_30s")
CASES = {
    "assumed (10 % loss, 40 m)": {},
    "30 % frame loss":           dict(d2d_loss=0.3),
    "60 % frame loss":           dict(d2d_loss=0.6),
    "range 15 m":                dict(d2d_range_m=15.0),
    "60 % loss + 15 m":          dict(d2d_loss=0.6, d2d_range_m=15.0),
}


def job(args):
    case, cond, chunk = args
    ForkliftLimit.MODE = "coop"
    cfg = site_cfg()
    return [run_episode(GENS[gi], random.Random(s), cfg, net=dataclasses.replace(condition(net, s, cond), **CASES[case]),
                        noise=noise) for gi, s, noise, net in chunk]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-gen", type=int, default=30)
    ap.add_argument("--out", default="results/d2d_sensitivity.json")
    a = ap.parse_args()
    eps = episodes_for(999_999, a.per_gen)
    out = {}
    with Pool(os.cpu_count() or 1) as pool:
        for case in CASES:
            for cond in CONDS:
                n = os.cpu_count() or 1
                res = sum(pool.map(job, [(case, cond, eps[i::n]) for i in range(n)]), [])
                s = score(res, collision_penalty=50)
                out.setdefault(case, {})[cond] = {k: s[k] for k in ("collisions", "conflicts", "throughput")}
                print(f"{case:28s} {cond:22s} coll {s['collisions']:3d}/{s['conflicts']}  thr {s['throughput']:.3f}", flush=True)
    json.dump({"episodes": len(eps), "mode": "coop", "cases": out}, open(os.path.join(ROOT, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
