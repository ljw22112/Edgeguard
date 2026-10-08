"""How much does the v0.8 local UWB fallback depend on the ranging assumptions?

    python -m sim.peer_ranging_sensitivity --per-gen 30 --out results/peer_ranging_sensitivity.json

Same held-out encounters as sim/failsafe_eval.py, mode failsafe_local_ttc_tag, conditions
mec_dead_8s and network_down_30s.  Each case changes the direct forklift <-> tag ranging:
update rate (crowding: more tags share the channel), missed rounds (NLOS, collisions),
noise, NLOS bias (ranges read long) and maximum range.
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
CASES = {
    "assumed (10 Hz, 10 % miss, 0.1 m, 30 m)": {},
    "5 Hz (crowded channel)":                  dict(uwb_peer_hz=5.0),
    "2 Hz (very crowded)":                     dict(uwb_peer_hz=2.0),
    "40 % missed rounds (NLOS)":               dict(uwb_peer_drop=0.4),
    "noise 0.3 m":                             dict(uwb_peer_sigma=0.3),
    "NLOS bias +0.5 m":                        dict(uwb_peer_bias=0.5, uwb_peer_sigma=0.2),
    "max range 12 m":                          dict(uwb_peer_range_m=12.0),
    "all bad (5 Hz, 40 %, 0.3 m, +0.5 m, 12 m)": dict(uwb_peer_hz=5.0, uwb_peer_drop=0.4, uwb_peer_sigma=0.3,
                                                      uwb_peer_bias=0.5, uwb_peer_range_m=12.0),
}


def job(args):
    case, cond, chunk = args
    ForkliftLimit.MODE = "failsafe_local_ttc_tag"
    cfg = site_cfg()
    out = []
    for gi, s, noise, net in chunk:
        n = dataclasses.replace(condition(net, s, cond), **CASES[case])
        out.append(run_episode(GENS[gi], random.Random(s), cfg, net=n, noise=noise))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-gen", type=int, default=30)
    ap.add_argument("--out", default="results/peer_ranging_sensitivity.json")
    a = ap.parse_args()
    eps = episodes_for(999_999, a.per_gen)
    out = {}
    with Pool(os.cpu_count() or 1) as pool:
        for case in CASES:
            for cond in ("mec_dead_8s", "network_down_30s"):
                n = os.cpu_count() or 1
                res = sum(pool.map(job, [(case, cond, eps[i::n]) for i in range(n)]), [])
                s = score(res, collision_penalty=50)
                out.setdefault(case, {})[cond] = {k: s[k] for k in ("collisions", "conflicts", "throughput", "lost_s_mean")}
                print(f"{case:45s} {cond:17s} coll {s['collisions']:3d}/{s['conflicts']}  thr {s['throughput']:.3f}", flush=True)
    ref = {"v0.7 failsafe (no local fallback)": {"mec_dead_8s": 75, "network_down_30s": 180}}
    json.dump({"episodes": len(eps), "mode": "failsafe_local_ttc_tag", "cases": out, "reference_collisions": ref},
              open(os.path.join(ROOT, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
