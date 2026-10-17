"""Where do forklifts and workers lose time?  Many-to-many episodes with a trace; every 0.1 s a forklift
runs below its nominal speed is booked to the reason in force:

  limit: <alert reason>      a speed limit from an alert (the tightest one, by the reason the MEC app gave)
  MEC silent (fail-safe)     no heartbeat / alert for 1.3 s (downlink loss): the truck slows or stops
  speeding up again          no limit any more, the truck accelerates back (1 m/s^2)

    python -m sim.efficiency_audit --episodes 100
Output: table of lost forklift-seconds by reason, and results/efficiency_audit.json.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.multi_sim import DT, run_episode                                     # noqa: E402


def categorize(reason):
    r = (reason or "").lower()
    for key, name in (("worker first", "worker first (truck holds)"), ("stepping aside", "worker stepping aside"),
                      ("a forklift still to pass", "worker waits for another truck"),
                      ("waiting at the lane edge", "pass waiting worker at walking pace"),
                      ("collision course", "collision course"), ("near miss predicted", "near miss predicted"),
                      ("forklift lane", "worker standing in the lane ahead"), ("in the lane", "worker in the lane"), ("occlu", "blind corner"), ("proximity", "proximity"),
                      ("standing", "standing worker ahead")):
        if key in r:
            return name
    return r[:40] or "unknown"


def episode(args):
    seed, n_w, n_f, over = args
    tr = []
    res = run_episode(seed, n_w, n_f, over=over, trace=tr, d2d=True)
    reason_of = {}                                  # (forklift, worker) -> reason of the last delivered alert
    lost = Counter()
    for e in tr:
        if e["type"] == "deliver" and e["to"].startswith("f"):
            reason_of[(e["to"], e["about"])] = e.get("reason")
        elif e["type"] == "fstep":
            vn = e["vn"]
            if vn <= 0.1:
                continue
            loss = (1 - min(1.0, e["v"] / vn)) * DT
            if loss <= 1e-6:
                continue
            if e["lim"] is None:
                cat = "speeding up again"
            elif e["silent"] and (not e["limits"] or e["lim"] < min(e["limits"].values())):
                cat = "MEC silent (fail-safe)"
            elif e["limits"]:
                w = min(e["limits"], key=lambda k: e["limits"][k])
                cat = "limit: " + categorize(reason_of.get((e["f"], w)))
            else:
                cat = "local D2D rule"
            lost[cat] += loss
    return res, dict(lost)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=100)
    ap.add_argument("--offset", type=int, default=200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--forklifts", type=int, default=4)
    ap.add_argument("--over", default="{}", help="policy overrides as JSON")
    a = ap.parse_args()
    seeds = [random.Random(7 + a.offset + i).randrange(1 << 30) for i in range(a.episodes)]
    with Pool(os.cpu_count() or 1) as p:
        out = p.map(episode, [(s, a.workers, a.forklifts, json.loads(a.over)) for s in seeds])
    lost = Counter()
    for _, l in out:
        lost.update(l)
    tot = {k: sum(r[k] for r, _ in out) for k in out[0][0]}
    total_lost = sum(lost.values())
    per = a.episodes * a.forklifts
    print(f"throughput {tot['forklift_m'] / tot['forklift_nominal_m']:.3f}, forklift lost {tot['forklift_lost_s'] / per:.2f} s "
          f"per forklift-episode, collisions {tot['collisions']}")
    for k, v in lost.most_common():
        print(f"  {v / per:6.2f} s  {100 * v / total_lost:5.1f} %  {k}")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json.dump({"episodes": a.episodes, "lost_s_per_forklift_episode": {k: round(v / per, 3) for k, v in lost.most_common()},
               "throughput": round(tot["forklift_m"] / tot["forklift_nominal_m"], 4), "collisions": tot["collisions"]},
              open(os.path.join(root, "results", "efficiency_audit.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
