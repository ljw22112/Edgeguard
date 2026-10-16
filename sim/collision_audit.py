"""Why do the remaining collisions happen?  Re-run the episodes that had one, with a trace, and print the
last seconds of every colliding pair: distance, speeds, the forklift's limit, what the worker was doing,
and every alert sent and delivered for that pair.

    python -m sim.collision_audit --episodes 200            # finds the colliding episodes itself
    python -m sim.collision_audit --seeds 143632254 831538941

Output: a readable timeline per collision, and results/collision_audit.json.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.multi_sim import run_episode                                        # noqa: E402
from sim.online_sim import R_COLLIDE                                         # noqa: E402


def find(args):
    seeds, n_w, n_f, over = args
    return [s for s in seeds if run_episode(s, n_w, n_f, over=over)["collisions"]]


def audit(seed, n_w, n_f, over=None, window=6.0):
    tr = []
    res = run_episode(seed, n_w, n_f, over=over, trace=tr)
    env = next(e for e in tr if e["type"] == "env")
    out = []
    for w, f in env["collided"]:
        steps = [e for e in tr if e["type"] == "pair" and e["w"] == w and e["f"] == f]
        t_hit = next(e["t"] for e in steps if e["d"] < R_COLLIDE)
        steps = [e for e in steps if t_hit - window <= e["t"] <= t_hit + 0.5]
        msgs = [e for e in tr if e["type"] in ("send", "deliver") and t_hit - window - 2 <= e["t"] <= t_hit + 0.5
                and {e["to"], e["about"]} == {w, f}]
        out.append({"seed": seed, "worker": w, "forklift": f, "t_hit": t_hit, "env": env, "steps": steps, "msgs": msgs})
    return res, out


def show(c):
    e = c["env"]
    print(f"\n=== seed {c['seed']}  {c['worker']} x {c['forklift']}  contact at t={c['t_hit']}  "
          f"(latency {e['lat_ms']}+-{e['jit_ms']} ms, uplink loss {e['up_loss']}, downlink loss {e['down_loss']}, noise {e['noise']} m)")
    events = [(s["t"], 0, s) for s in c["steps"]] + [(m["t"], 1, m) for m in c["msgs"]]
    last = None
    for t, kind, x in sorted(events, key=lambda z: (z[0], z[1])):
        if kind == 1:
            tag = "LOST " if x.get("lost") else ""
            print(f"   {t:5.1f}  {x['type']:7s} {tag}{x['ev']:8s} -> {x['to']}  {x.get('acts') or ''}")
        else:
            row = (x["d"], x["wv"], x["fv"], x["flim"], x["wstop"], x["aside"], tuple(x["holds"]), x["blocked"])
            if row == last:
                continue
            last = row
            print(f"   {t:5.1f}  d={x['d']:5.2f}  worker v={x['wv']:.2f}{' STOP' if x['wstop'] else ''}{' ASIDE' if x['aside'] else ''}"
                  f"{' BLOCKED' if x['blocked'] else ''} holds={x['holds']}  forklift v={x['fv']:.2f} limit={x['flim']}"
                  f"  w={x['wpos']} f={x['fpos']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--forklifts", type=int, default=4)
    ap.add_argument("--seeds", type=int, nargs="*")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    seeds = a.seeds
    if not seeds:
        all_seeds = [random.Random(7 + i).randrange(1 << 30) for i in range(a.episodes)]
        n = os.cpu_count() or 1
        with Pool(n) as p:
            seeds = sum(p.map(find, [(all_seeds[i::n], a.workers, a.forklifts, None) for i in range(n)]), [])
    cases = []
    for s in seeds:
        _, cs = audit(s, a.workers, a.forklifts)
        cases += cs
    for c in cases:
        if not a.quiet:
            show(c)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json.dump(cases, open(os.path.join(root, "results", "collision_audit.json"), "w"), indent=1)
    print(f"\n{len(cases)} collisions in {len(seeds)} episodes")


if __name__ == "__main__":
    main()
