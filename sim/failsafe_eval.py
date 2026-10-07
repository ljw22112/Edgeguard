"""A/B of the forklift's device-side rules under MEC outages (fast closed loop).

    python -m sim.failsafe_eval --per-gen 30 --out results/failsafe_eval.json

legacy   : v0.6 - hold the last speed limit, lift it after 5 s without alerts
failsafe : edgeguard/device_policy.py - 1 s heartbeat; MEC silent -> hold the plan,
           silent > 2 s -> stop; MEC alive but no refresh 5 s -> lift (lost "clear")
failsafe_creep / failsafe_stop : rejected variants (crawl / stop as soon as silent)

Conditions (same held-out encounters and network draws for both modes):
  normal         randomised network (latency, jitter, loss) as in policy validation
  mec_restart    + MEC app dies for 1.7 s at a random moment 2-7 s into the encounter
                 and restarts with empty state (measured restart: 1.4-2.2 s)
  restart_loss20 + 20 % downlink loss on top of the restart
  mec_dead_8s    MEC app down for 8 s (crash, host reboot)

The silence actions crawl / stop and an early 2.2 s lift were evaluated too and rejected
(more collisions; see the "rejected" entry in the results file).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import random
import sys
from multiprocessing import Pool

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard.device_policy import ForkliftLimit                   # noqa: E402
from edgeguard.risk import RiskConfig                               # noqa: E402
from sim.closed_loop import run_episode, score                      # noqa: E402
from sim.train_policy import GENS, episodes_for                     # noqa: E402

MODES = ("legacy", "failsafe", "failsafe_creep", "failsafe_stop")
REJECTED = {"early_lift_2.2s": "normal 24 / restart 32 / restart+loss 52 collisions of 180 "
                               "(legacy 19 / 30 / 43) - evaluated before ALERT_STALE_S went back to 5 s"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def site_cfg():
    r = yaml.safe_load(open(os.path.join(ROOT, "config", "site.yaml")))["risk"]
    names = {f.name for f in dataclasses.fields(RiskConfig)}
    return RiskConfig(**{k: v for k, v in r.items() if k in names})


def condition(net, seed, name):
    net = dataclasses.replace(net)
    if name in ("mec_restart", "restart_loss20"):
        t0 = random.Random(seed ^ 0x5EED).uniform(2.0, 7.0)
        net.mec_down = (t0, t0 + 1.7)
    if name == "mec_dead_8s":
        t0 = random.Random(seed ^ 0x5EED).uniform(2.0, 7.0)
        net.mec_down = (t0, t0 + 8.0)
    if name == "restart_loss20":
        net.down_loss = max(net.down_loss, 0.2)
    return net


def job(args):
    mode, cond, chunk = args
    ForkliftLimit.MODE = mode
    cfg = site_cfg()
    return [run_episode(GENS[gi], random.Random(s), cfg, net=condition(net, s, cond), noise=noise)
            for gi, s, noise, net in chunk]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-gen", type=int, default=30)
    ap.add_argument("--out", default="results/failsafe_eval.json")
    a = ap.parse_args()
    eps = episodes_for(999_999, a.per_gen)
    out = {}
    with Pool(os.cpu_count() or 1) as pool:
        for cond in ("normal", "mec_restart", "restart_loss20", "mec_dead_8s"):
            for mode in MODES:
                n = os.cpu_count() or 1
                res = sum(pool.map(job, [(mode, cond, eps[i::n]) for i in range(n)]), [])
                s = score(res, collision_penalty=50)
                out.setdefault(cond, {})[mode] = s
                print(f"{cond:15s} {mode:9s} coll {s['collisions']:3d}/{s['conflicts']}  recall {s['recall']:.3f}  "
                      f"F2 {s['f_beta']:.3f}  thr {s['throughput']:.3f}  lost {s['lost_s_mean']:.2f} s", flush=True)
    json.dump({"episodes": len(eps), "results": out, "rejected": REJECTED}, open(os.path.join(ROOT, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
