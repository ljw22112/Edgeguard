"""False alarms (v1.2): route sharing and the standing-still gate, fast closed loop.

    python -m sim.false_alarm_eval --per-gen 100 --out results/false_alarm_eval.json

Every false alarm now costs the worker a WAIT and the forklift a slow-down, so they matter more
than before.  Two sources were addressed:
  route   : the forklift's fleet system (or the driver's tablet) shares its planned route; the risk
            engine follows it instead of guessing with CTRV - a truck about to turn away no longer
            alarms the worker straight ahead, one about to turn into an aisle warns earlier
            (edgeguard/predict.py RoutePredictor).  Optional: needs an integration on site.
  still   : a worker slower than still_speed (0.4 m/s) is predicted to stand still; UWB noise
            otherwise "walks" standing pickers into the lane (edgeguard/risk.py).
Remaining: a worker who stops by himself just short of the lane (worker_yields) cannot be told
apart at alert time - people decelerate within the last second.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sim.closed_loop as cl                                        # noqa: E402
from edgeguard.device_policy import ForkliftLimit                   # noqa: E402
from sim.failsafe_eval import site_cfg                              # noqa: E402
from sim.train_policy import GENS, episodes_for                     # noqa: E402

VARIANTS = {"v1.2 without the still gate": (False, 0.0), "+ still gate (v1.2)": (False, None),
            "+ still gate + route sharing": (True, None)}
SEEDS = (999_999, 424_242)


def job(args):
    route, still, chunk = args
    from sim.online_sim import Mover
    ForkliftLimit.MODE, Mover.UX = "coop", "hold"
    cl.ROUTE_SHARE = route
    cfg = site_cfg()
    if still is not None:
        cfg = dataclasses.replace(cfg, still_speed=still)
    return [cl.run_episode(GENS[gi], random.Random(s), cfg, net=net, noise=noise) for gi, s, noise, net in chunk]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-gen", type=int, default=100)
    ap.add_argument("--out", default="results/false_alarm_eval.json")
    a = ap.parse_args()
    n = os.cpu_count() or 1
    out = {"per_gen": a.per_gen, "seeds": SEEDS, "variants": {}}
    with Pool(n) as pool:
        eps = sum((episodes_for(sd, a.per_gen) for sd in SEEDS), [])
        for name, (route, still) in VARIANTS.items():
            res = sum(pool.map(job, [(route, still, eps[i::n]) for i in range(n)]), [])
            s = cl.score(res, collision_penalty=50)
            fa = collections.Counter(r.scenario for r in res if not r.conflict and r.first_alert is not None)
            out["variants"][name] = row = {
                "collisions": s["collisions"], "conflicts": s["conflicts"], "false_alarms": s["false_alarms"],
                "non_conflict": s["episodes"] - s["conflicts"], "recall": round(s["recall"], 4),
                "throughput": round(s["throughput"], 4), "forklift_lost_s": round(s["lost_s_mean"], 2),
                "worker_lost_s": round(s["worker_wait_s_mean"], 2), "false_alarms_by_scenario": dict(fa)}
            print(f"{name:32s} FA {row['false_alarms']}/{row['non_conflict']}  coll {row['collisions']}/{row['conflicts']}  "
                  f"recall {row['recall']:.3f}  thr {row['throughput']:.3f}  {dict(fa)}", flush=True)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json.dump(out, open(os.path.join(root, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
