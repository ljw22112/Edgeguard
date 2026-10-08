"""Blind corners: does knowing the site map help?

    python -m sim.occlusion_eval --per-gen 60 --out results/occlusion_eval.json

Same corner geometry with a rack filling the corner (blind) and without (open).  People yield on
their own when they can see each other (sim/closed_loop.py human_vision) - which the rack takes
away.  Compared: the risk engine without the map vs with it (occluded pairs get +occl_t_margin on
the warning / danger thresholds).  Fast closed loop, randomised network as in policy validation.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.closed_loop import Net, run_episode, score                 # noqa: E402
from sim.failsafe_eval import site_cfg                              # noqa: E402
from sim.scenarios import CORNER_GENERATORS                         # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def episodes(per_gen, seed=777_001):
    rng = random.Random(seed)
    out = []
    for gi in range(len(CORNER_GENERATORS)):
        for _ in range(per_gen):
            net = Net(latency_ms=rng.uniform(40, 120), jitter_ms=rng.uniform(5, 40),
                      up_loss=rng.uniform(0, 0.05), down_loss=rng.uniform(0, 0.05))
            out.append((gi, rng.randrange(1 << 30), rng.uniform(0.1, 0.25), net))
    return out


VARIANTS = {
    "no map":                   (False, {}),
    "map: time +1 s":           (True, dict(occl_t_margin=1.0)),
    "map: r +0.3 m, debounce 1": (True, dict(occl_t_margin=0.0, occl_r_margin=0.3, occl_debounce=1)),
    "map: r +0.5 m, debounce 1": (True, dict(occl_t_margin=0.0, occl_r_margin=0.5, occl_debounce=1)),
    "map: r +0.8 m, debounce 1": (True, dict(occl_t_margin=0.0, occl_r_margin=0.8, occl_debounce=1)),
}


def job(args):
    variant, vision, chunk = args
    map_aware, over = VARIANTS[variant]
    cfg = site_cfg()
    for k, v in over.items():
        setattr(cfg, k, v)
    return [run_episode(CORNER_GENERATORS[gi], random.Random(s), cfg, net=net, noise=noise,
                        map_aware=map_aware, human_vision=vision) for gi, s, noise, net in chunk]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-gen", type=int, default=60)
    ap.add_argument("--out", default="results/occlusion_eval.json")
    a = ap.parse_args()
    eps = episodes(a.per_gen)
    out = {}
    n = os.cpu_count() or 1
    with Pool(n) as pool:
        for vision in (True, False):
            for label in VARIANTS:
                res = sum(pool.map(job, [(label, vision, eps[i::n]) for i in range(n)]), [])
                row = {}
                for grp in ("blind", "open"):
                    sub = [r for r in res if r.scenario.startswith(grp)]
                    s = score(sub, collision_penalty=50)
                    row[grp] = {k: s[k] for k in ("collisions", "conflicts", "false_alarms", "recall",
                                                  "throughput", "lost_s_mean")}
                key = f"{'people see each other' if vision else 'no human yielding'} | {label}"
                out[key] = row
                print(f"{key:45s} blind: coll {row['blind']['collisions']:3d}/{row['blind']['conflicts']} "
                      f"FA {row['blind']['false_alarms']:3d} thr {row['blind']['throughput']:.3f} | "
                      f"open: coll {row['open']['collisions']:3d}/{row['open']['conflicts']} "
                      f"FA {row['open']['false_alarms']:3d} thr {row['open']['throughput']:.3f}", flush=True)
    json.dump({"episodes": len(eps), "results": out}, open(os.path.join(ROOT, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
