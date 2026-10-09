"""Worker WAIT-until-GO tag (v1.1) vs the v1.0 vibration burst, fast closed loop.

    python -m sim.worker_cue_eval --per-gen 100 --out results/worker_cue_eval.json

Why: the remaining collisions of v1.0 were almost all *timely* alerts - the buzzed worker stopped
for ~2 s, walked on, and met the forklift whose speed had been planned for a worker who stays.
Variants (same held-out encounters, randomised network, two seed sets):
  v1.0 buzz          : burst, worker stops ~2 s
  hold               : tag WAITs until clear (gives up after 2.5 s without a message)
  hold + keep-alive  : MEC app re-sends `wait` every second while the alert is active
  hold + keep-alive + GO check (v1.1): no clear while walking on would cross the forklift
Compliance sweep: share of workers who obey a WAIT (others behave as with the burst).
Costs are reported for both sides: forklift seconds lost and worker seconds lost per encounter.
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
from sim.failsafe_eval import site_cfg                              # noqa: E402
from sim.train_policy import GENS, episodes_for                     # noqa: E402

VARIANTS = {   # name: (ux, cfg overrides)
    "v1.0 buzz": ("buzz", {"wait_keepalive": False, "go_check": False}),
    "hold": ("hold", {"wait_keepalive": False, "go_check": False}),
    "hold + keep-alive": ("hold", {"wait_keepalive": True, "go_check": False}),
    "v1.1 hold + keep-alive + GO check": ("hold", {"wait_keepalive": True, "go_check": True}),
}
SEEDS = (999_999, 424_242)


def job(args):
    ux, over, comply, chunk = args
    from sim.online_sim import Mover
    ForkliftLimit.MODE = "coop"
    Mover.UX, Mover.COMPLY = ux, comply
    cfg = dataclasses.replace(site_cfg(), **over)
    return [run_episode(GENS[gi], random.Random(s), cfg, net=net, noise=noise) for gi, s, noise, net in chunk]


def run(pool, eps, ux, over, comply):
    n = os.cpu_count() or 1
    return sum(pool.map(job, [(ux, over, comply, eps[i::n]) for i in range(n)]), [])


def summary(res):
    s = score(res, collision_penalty=50)
    keep = ("collisions", "conflicts", "episodes", "throughput", "lost_s_mean", "worker_wait_s_mean",
            "false_alarms", "recall", "precision")
    return {k: (round(s[k], 4) if isinstance(s[k], float) else s[k]) for k in keep}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-gen", type=int, default=100)
    ap.add_argument("--out", default="results/worker_cue_eval.json")
    a = ap.parse_args()
    out = {"per_gen": a.per_gen, "seeds": SEEDS, "variants": {}, "compliance": {}}
    with Pool(os.cpu_count() or 1) as pool:
        eps_all = [episodes_for(sd, a.per_gen) for sd in SEEDS]
        for name, (ux, over) in VARIANTS.items():
            res = sum((run(pool, eps, ux, over, 1.0) for eps in eps_all), [])
            out["variants"][name] = s = summary(res)
            print(f"{name:36s} coll {s['collisions']:3d}/{s['conflicts']}  thr {s['throughput']:.3f}  "
                  f"forklift lost {s['lost_s_mean']:.2f} s  worker lost {s['worker_wait_s_mean']:.2f} s", flush=True)
        ux, over = VARIANTS["v1.1 hold + keep-alive + GO check"]
        for comply in (0.85, 0.7, 0.5):
            res = sum((run(pool, eps, ux, over, comply) for eps in eps_all), [])
            out["compliance"][str(comply)] = s = summary(res)
            print(f"v1.1, {int(comply * 100)} % obey WAIT{'':17s} coll {s['collisions']:3d}/{s['conflicts']}  "
                  f"thr {s['throughput']:.3f}  forklift lost {s['lost_s_mean']:.2f} s  "
                  f"worker lost {s['worker_wait_s_mean']:.2f} s", flush=True)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json.dump(out, open(os.path.join(root, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
