"""EdgeGuard policies under normal and exceptional conditions on the many-to-many floor (sim/multi_sim.py).

    python -m sim.robust_eval --episodes 100 --offset 7000 --policy current --policy results/policy.json

Every scenario runs the same episodes (seeds offset+...), only the condition changes:
  normal         the usual randomised network (40-220 ms, up to 20 % / 10 % loss), sensing noise 0.1-0.35 m
  comply_85      workers ignore 15 % of the alerts (stop ~2 s on the buzz and walk on)
  comply_70      ... 30 %
  bad_network    300-600 ms latency, 20-40 % uplink and 15-30 % downlink loss
  mec_restart    the MEC app is silent for 2.5 s at a random moment and comes back without its alert state
  noisy_uwb      0.35-0.6 m position noise
  dense          12 workers and 6 forklifts
  attentive      drivers brake for someone right in front of the truck (1 s reaction)
A policy is robust if it has no collision in any scenario.  Reported per scenario: collisions, close passes
(< 1.5 m), forklift throughput, worker seconds lost per worker-episode, alarms per episode.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.multi_sim import run_episode                                         # noqa: E402

D2D = True        # the devices' D2D fall-back is part of the system (sim/multi_sim.py run_episode d2d)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIOS = {   # name: (workers, forklifts, compliance, attentive, stress)
    "normal": (8, 4, 1.0, False, {}),
    "comply_85": (8, 4, 0.85, False, {}),
    "comply_70": (8, 4, 0.70, False, {}),
    "bad_network": (8, 4, 1.0, False, {"lat_ms": (300, 600), "jit_ms": (20, 80), "up_loss": (0.2, 0.4),
                                       "down_loss": (0.15, 0.3)}),
    "mec_restart": (8, 4, 1.0, False, {"mec_down_s": 2.5}),
    "noisy_uwb": (8, 4, 1.0, False, {"noise": (0.35, 0.6)}),
    "dense": (12, 6, 1.0, False, {}),
    "attentive": (8, 4, 1.0, True, {}),
}


def job(a):
    seed, sc, over = a
    n_w, n_f, comply, att, stress = SCENARIOS[sc]
    r = run_episode(seed, n_w, n_f, comply=comply, over=over, attentive=att, stress=stress, d2d=D2D)
    r["_w"] = n_w
    return r


def evaluate(over, episodes, offset, scenarios=None, pool=None):
    seeds = [random.Random(7 + offset + i).randrange(1 << 30) for i in range(episodes)]
    out = {}
    own = pool is None
    pool = pool or Pool(os.cpu_count() or 1)
    try:
        for sc in scenarios or SCENARIOS:
            res = pool.map(job, [(s, sc, over) for s in seeds])
            tot = {k: sum(r[k] for r in res) for k in ("collisions", "near", "forklift_m", "forklift_nominal_m",
                                                       "worker_wait_s", "alarms", "conflicts", "_w")}
            out[sc] = {"collisions": tot["collisions"], "close_passes": tot["near"], "conflicts": tot["conflicts"],
                       "throughput": round(tot["forklift_m"] / tot["forklift_nominal_m"], 4),
                       "worker_lost_s": round(tot["worker_wait_s"] / tot["_w"], 3),
                       "alarms_per_episode": round(tot["alarms"] / episodes, 2)}
    finally:
        if own:
            pool.close()
    return out


def load_policy(spec):
    if spec == "current":
        return {}
    d = json.load(open(spec if os.path.isabs(spec) else os.path.join(ROOT, spec)))
    return d.get("policy", d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=100)
    ap.add_argument("--offset", type=int, default=7000)
    ap.add_argument("--policy", action="append", default=None, help="'current' (config/site.yaml) or a JSON file")
    ap.add_argument("--out", default="results/robust_eval.json")
    a = ap.parse_args()
    res = {}
    for spec in a.policy or ["current"]:
        res[spec] = evaluate(load_policy(spec), a.episodes, a.offset)
        for sc, r in res[spec].items():
            print(f"{spec:30s} {sc:12s} coll {r['collisions']:3d}  close {r['close_passes']:3d}  thr {r['throughput']:.3f}  "
                  f"worker {r['worker_lost_s']:.2f} s  alarms {r['alarms_per_episode']:.1f}", flush=True)
    json.dump({"episodes": a.episodes, "seed_offset": a.offset, "scenarios": {k: list(v[:4]) + [v[4]] for k, v in SCENARIOS.items()},
               "results": res}, open(os.path.join(ROOT, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
