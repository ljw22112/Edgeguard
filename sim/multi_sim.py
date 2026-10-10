"""Many workers x many forklifts on one floor, fast closed loop (the other sims are one pair).

    python -m sim.multi_sim --episodes 200 --out results/multi_sim.json

A 36 x 24 m floor with three aisles along x (y = -8, 0, 8) and three cross aisles along y
(x = -12, 0, 12).  Every episode (25 s) has N_F forklifts driving through on random aisles and
N_W workers crossing aisles, walking along them, or standing at a pick face, all starting at
random times - so a worker meets several forklifts and a forklift several workers at once.

Same pieces as sim/closed_loop.py (tracker, risk engine on every pair, alert policy, reacting
devices, randomised network).  What this adds is the many-to-many bookkeeping on the devices:
  forklift: one speed plan per worker, the tightest applies (edgeguard/device_policy.py)
  worker  : one WAIT per forklift, GO only when all have cleared (edgeguard/worker_cue.py)
Variant "single" reproduces devices that keep ONE plan / ONE wait: a clear about one worker lifts
the limit another worker needs, a clear from one forklift releases the worker into another.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard.alerting import AlertState, decide                  # noqa: E402
from edgeguard.device_policy import ForkliftLimit                  # noqa: E402
from edgeguard.risk import RiskEngine                              # noqa: E402
from edgeguard.tracking import Track                               # noqa: E402
from sim.failsafe_eval import site_cfg                             # noqa: E402
from sim.online_sim import Mover, Path, R_COLLIDE, R_CONTACT       # noqa: E402

DT, T_END = 0.1, 25.0
AISLES_Y, AISLES_X = (-8.0, 0.0, 8.0), (-12.0, 0.0, 12.0)
HALF_W, HALF_H = 18.0, 12.0


def _times():
    return [i * DT for i in range(int(round(T_END / DT)) + 1)]


def _forklift(rng, times):
    v = rng.uniform(1.5, 3.0)
    t0 = rng.uniform(0.0, 10.0)
    if rng.random() < 0.5:                                    # along x
        y, d = rng.choice(AISLES_Y), rng.choice((-1, 1))
        x0 = -d * (HALF_W + 8)
        pts = [(x0 + d * v * max(0.0, t - t0), y) for t in times]
        th = 0.0 if d > 0 else math.pi
    else:                                                     # along y
        x, d = rng.choice(AISLES_X), rng.choice((-1, 1))
        y0 = -d * (HALF_H + 8)
        pts = [(x, y0 + d * v * max(0.0, t - t0)) for t in times]
        th = math.pi / 2 if d > 0 else -math.pi / 2
    return pts, [(th, 1, 0.0)] * len(times)


def _worker(rng, times):
    v, t0 = rng.uniform(0.8, 1.4), rng.uniform(0.0, 12.0)
    kind = rng.random()
    if kind < 0.15:                                           # picker standing at a pick face
        if rng.random() < 0.5:
            p = (rng.uniform(-HALF_W, HALF_W), rng.choice(AISLES_Y) + rng.choice((-1, 1)) * rng.uniform(1.8, 2.6))
        else:
            p = (rng.choice(AISLES_X) + rng.choice((-1, 1)) * rng.uniform(1.8, 2.6), rng.uniform(-HALF_H, HALF_H))
        return [p] * len(times)
    if kind < 0.7:                                            # crossing an aisle
        if rng.random() < 0.5:
            y = rng.choice(AISLES_Y)
            x, d = rng.uniform(-HALF_W + 2, HALF_W - 2), rng.choice((-1, 1))
            start, u = (x, y - d * rng.uniform(4, 7)), (0.0, d)
        else:
            x = rng.choice(AISLES_X)
            y, d = rng.uniform(-HALF_H + 2, HALF_H - 2), rng.choice((-1, 1))
            start, u = (x - d * rng.uniform(4, 7), y), (d, 0.0)
        length = rng.uniform(8, 14)
    else:                                                     # walking along an aisle (beside the lane)
        if rng.random() < 0.5:
            y = rng.choice(AISLES_Y) + rng.uniform(-1.2, 1.2)
            d = rng.choice((-1, 1))
            start, u = (rng.uniform(-HALF_W, HALF_W), y), (d, 0.0)
        else:
            x = rng.choice(AISLES_X) + rng.uniform(-1.2, 1.2)
            d = rng.choice((-1, 1))
            start, u = (x, rng.uniform(-HALF_H, HALF_H)), (0.0, d)
        length = rng.uniform(6, 12)
    out = []
    for t in times:
        s = min(length, v * max(0.0, t - t0))
        out.append((start[0] + u[0] * s, start[1] + u[1] * s))
    return out


def run_episode(seed, n_w, n_f, ux="hold", per_pair=True, comply=1.0, see_obstacles=True, min_move=None, over=None):
    rng = random.Random(seed)
    Mover.UX, Mover.COMPLY = ux, comply
    ForkliftLimit.MODE = "coop"
    cfg = site_cfg()
    if min_move is not None:
        cfg.min_move = min_move
    for k, v in (over or {}).items():
        setattr(cfg, k, v)
    times = _times()
    lat_ms, jit_ms = rng.uniform(40, 220), rng.uniform(5, 40)
    up_loss, down_loss, noise = rng.uniform(0, 0.2), rng.uniform(0, 0.1), rng.uniform(0.1, 0.35)
    wp = {f"w{i}": _worker(rng, times) for i in range(n_w)}
    fp = {f"f{j}": _forklift(rng, times) for j in range(n_f)}
    movers = {k: Mover(k, "worker", Path(p)) for k, p in wp.items()}
    movers.update({k: Mover(k, "forklift", Path(p, m)) for k, (p, m) in fp.items()})
    nominal = {(w, f): min(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(wp[w], fp[f][0]))
               for w in wp for f in fp}
    engine = RiskEngine(cfg, "guidance_ctrv")
    states, pending, actual = {}, [], {k: 1e9 for k in nominal}
    last_hb = -1e9
    key = (lambda other: other) if per_pair else (lambda other: "")
    for t in times:
        keep = []
        for due, ev, acts, to, other in pending:
            if due > t:
                keep.append((due, ev, acts, to, other))
                continue
            m = movers[to]
            if ev == "hb":
                m.pending.append((t, "hb", None, ""))
            elif m.kind == "forklift":
                m.on_alert(t, ev, (acts.get(to) or {}).get("speed_limit"), src=key(other))
            else:
                wa = acts.get(to) or {}
                m.on_alert(t, ev, wa.get("aside"), vibrate=wa.get("vibrate"), rng=rng, src=key(other))
        pending = keep
        if see_obstacles:                      # nobody walks into a truck standing right in front of him
            for w in wp:
                mw = movers[w]
                (xw, yw), (xa, ya) = mw.path.pos(mw.s), mw.path.pos(min(mw.path.end, mw.s + 0.3))
                ux, uy = xa - xw, ya - yw
                xw, yw = mw.pos()
                un = math.hypot(ux, uy)
                mw.blocked = False
                if un < 1e-6:
                    continue
                for f in fp:
                    mf = movers[f]
                    if mf.v > 0.3:
                        continue
                    xf, yf = mf.pos()
                    dx, dy = xf - xw, yf - yw
                    d = math.hypot(dx, dy)
                    if d < 2.2 and (dx * ux + dy * uy) / (un * max(d, 1e-6)) > 0.5:
                        mw.blocked = True
        for m in movers.values():
            m.step(t, DT)
        pos = {k: m.pos() for k, m in movers.items()}
        for (w, f) in actual:
            actual[(w, f)] = min(actual[(w, f)], math.hypot(pos[w][0] - pos[f][0], pos[w][1] - pos[f][1]))
        for k, m in movers.items():
            if rng.random() < up_loss:
                continue
            x, y = pos[k][0] + rng.gauss(0, noise), pos[k][1] + rng.gauss(0, noise)
            if m.kind == "worker":
                engine.update(Track, k, "worker", t, x=x, y=y)
            else:
                smp = m.sample()
                engine.update(Track, k, "forklift", t, x=x, y=y, speed=smp["speed"] + rng.gauss(0, 0.05),
                              heading=smp["heading"] + rng.gauss(0, 0.035), yaw_rate=smp["yaw_rate"])
        if t < 0.5:
            continue

        def send(ev, acts, to, other):
            if rng.random() >= down_loss:
                pending.append((t + max(0.0, rng.gauss(lat_ms, jit_ms)) / 1000, ev, acts, to, other))
        if t - last_hb >= 1.0 - 1e-9:
            last_hb = t
            for f in fp:
                send("hb", {}, f, "")
        for r in engine.evaluate():
            st = states.setdefault((r.worker, r.forklift), AlertState())
            others = [tr for tr in engine.tracks.values() if tr.kind == "forklift" and tr.x is not None]
            ev, acts = decide(st, r, engine.tracks.get(r.worker), engine.tracks.get(r.forklift), cfg, t, others=others)
            if ev:
                send(ev, acts, r.worker, r.forklift)
                if ev not in ("wait", "release", "aside"):
                    send(ev, acts, r.forklift, r.worker)
    fl = [m for m in movers.values() if m.kind == "forklift"]
    wk = [m for m in movers.values() if m.kind == "worker"]
    nom = sum(_nominal_s(m.path) for m in fl)
    return {"conflicts": sum(d < R_CONTACT for d in nominal.values()),
            "collisions": sum(actual[k] < R_COLLIDE for k in nominal),
            "collisions_in_conflict": sum(actual[k] < R_COLLIDE for k, d in nominal.items() if d < R_CONTACT),
            "forklift_m": sum(min(m.s, _nominal_s(m.path)) for m in fl), "forklift_nominal_m": nom,
            "forklift_lost_s": sum(m.lost_s for m in fl), "worker_wait_s": sum(m.wait_s for m in wk),
            "pairs_close": sum(d < 4.0 for d in nominal.values())}


def _nominal_s(path):
    s, t = 0.0, 0.0
    while t < T_END and s < path.end:
        s += path.v_nom(s) * DT
        t += DT
    return s


OFF = {"wait_keepalive": False, "go_check": False, "min_move": 0.0, "aside_cue": False, "still_speed": 0.0}
V11 = {"wait_keepalive": True, "go_check": True, "min_move": 0.0, "aside_cue": False, "still_speed": 0.0}
VARIANTS = {   # name: (worker UX, one plan per pair on the devices, policy overrides)
    "v1.0 buzz": ("buzz", False, OFF),
    "v1.1 WAIT/GO": ("hold", False, V11),
    "v1.2 (per pair + standoffs + STEP ASIDE + still gate)": ("hold", True, {}),
    "v1.2 without per-pair plans": ("hold", False, {}),
    "v1.2 without the 0.3 m/s stop": ("hold", True, {"min_move": 0.0}),
    "v1.2 without STEP ASIDE": ("hold", True, {"aside_cue": False}),
    "v1.2 without the still gate": ("hold", True, {"still_speed": 0.0}),
}


def job(args):
    seeds, n_w, n_f, ux, per_pair, comply, over = args
    return [run_episode(s, n_w, n_f, ux, per_pair, comply, over=over) for s in seeds]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--forklifts", type=int, default=4)
    ap.add_argument("--out", default="results/multi_sim.json")
    a = ap.parse_args()
    seeds = [random.Random(7 + i).randrange(1 << 30) for i in range(a.episodes)]
    n = os.cpu_count() or 1
    out = {"episodes": a.episodes, "workers": a.workers, "forklifts": a.forklifts, "variants": {}}
    with Pool(n) as pool:
        for name, (ux, per_pair, over) in VARIANTS.items():
            res = sum(pool.map(job, [(seeds[i::n], a.workers, a.forklifts, ux, per_pair, 1.0, over) for i in range(n)]), [])
            tot = {k: sum(r[k] for r in res) for k in res[0]}
            s = {"collisions": tot["collisions"], "conflicts": tot["conflicts"],
                 "collisions_in_conflict": tot["collisions_in_conflict"],
                 "throughput": round(tot["forklift_m"] / tot["forklift_nominal_m"], 4),
                 "forklift_lost_s_per_forklift": round(tot["forklift_lost_s"] / (a.episodes * a.forklifts), 2),
                 "worker_wait_s_per_worker": round(tot["worker_wait_s"] / (a.episodes * a.workers), 2)}
            out["variants"][name] = s
            print(f"{name:50s} collisions {s['collisions']:3d} (conflicts {s['conflicts']})  thr {s['throughput']:.3f}  "
                  f"forklift lost {s['forklift_lost_s_per_forklift']:.2f} s  worker lost {s['worker_wait_s_per_worker']:.2f} s",
                  flush=True)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json.dump(out, open(os.path.join(root, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
