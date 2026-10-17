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


# --- systems used on sites today (sim/site_compare.py), on the same floor and episodes -------------------
# "none"        no system: drivers and walkers rely on their own attention
# "speed_zone"  automated speed zoning: trucks capped at pedestrian-area speed (5 km/h) in the shared aisles
# "proximity"   UWB proximity warning (tag on the worker, anchor on the truck): inside the warning zone the
#               truck is slowed to walking speed and the tag vibrates, inside the danger zone the truck stops;
#               direction-agnostic, the tag buzzes (the worker stops ~2 s and walks on)
ZONE_KMH = 5.0
PROX_WARN_M, PROX_DANGER_M, PROX_SLOW_MPS = 6.0, 3.0, 1.4
PROX_TIGHT = (4.0, 2.0)    # "proximity_tight": zones narrowed to cut nuisance alarms
UNNEEDED_M = 4.0           # an alarm for a pair that would not have come closer than this anyway


def run_episode(seed, n_w, n_f, ux="hold", per_pair=True, comply=1.0, see_obstacles=True, min_move=None, over=None,
                trace=None, system="edgeguard", attentive=False, stress=None, d2d=False):
    """d2d: the devices also broadcast their state peer to peer (ESP-NOW / sidelink, 10 Hz, 25 m, 5 % loss) and
    apply the cooperative local rule while the MEC app is silent (edgeguard/device_policy.py, mode "coop") -
    trucks on the closest point of approach, tags vibrate their worker."""
    """trace: a list that receives, for analysis (sim/collision_audit.py), every alert sent / delivered and
    a per-step snapshot of each worker-forklift pair closer than 8 m."""
    rng = random.Random(seed)
    if system.startswith("proximity"):
        ux = "buzz"
    warn_m, danger_m = PROX_TIGHT if system == "proximity_tight" else (PROX_WARN_M, PROX_DANGER_M)
    Mover.UX, Mover.COMPLY = ux, comply
    Mover.NEW_HOLD_ON_GO = bool(d2d)           # the tag model of the robust evaluation (WaitCue behaviour)
    ForkliftLimit.MODE = "coop"
    ForkliftLimit.AEB = bool(d2d) and system == "edgeguard"   # the always-on D2D emergency brake needs D2D states
    cfg = site_cfg()
    if min_move is not None:
        cfg.min_move = min_move
    for k, v in (over or {}).items():
        setattr(cfg, k, v)
    times = _times()
    lat_ms, jit_ms = rng.uniform(40, 220), rng.uniform(5, 40)
    up_loss, down_loss, noise = rng.uniform(0, 0.2), rng.uniform(0, 0.1), rng.uniform(0.1, 0.35)
    # stress scenarios (sim/robust_eval.py): the same episode under worse conditions; drawn from their own
    # generator so the floor, the people and the trucks stay those of the normal episode
    stress = stress or {}
    srng = random.Random(seed ^ 0x57E55)
    if "lat_ms" in stress:
        lat_ms, jit_ms = srng.uniform(*stress["lat_ms"]), srng.uniform(*stress.get("jit_ms", (5, 40)))
    if "up_loss" in stress:
        up_loss = srng.uniform(*stress["up_loss"])
    if "down_loss" in stress:
        down_loss = srng.uniform(*stress["down_loss"])
    if "noise" in stress:
        noise = srng.uniform(*stress["noise"])
    mec_down = None
    if "mec_down_s" in stress:                 # the MEC app is silent (restart / host fault) for this long
        t0 = srng.uniform(3.0, 15.0)
        mec_down = (t0, t0 + stress["mec_down_s"])
    wp = {f"w{i}": _worker(rng, times) for i in range(n_w)}
    fp = {f"f{j}": _forklift(rng, times) for j in range(n_f)}
    movers = {k: Mover(k, "worker", Path(p)) for k, p in wp.items()}
    movers.update({k: Mover(k, "forklift", Path(p, m)) for k, (p, m) in fp.items()})
    if system == "speed_zone":                 # trucks enter the zone already at the zone speed
        for k in fp:
            movers[k].v = min(movers[k].v, ZONE_KMH / 3.6)
    nominal = {(w, f): min(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(wp[w], fp[f][0]))
               for w in wp for f in fp}
    engine = RiskEngine(cfg, "guidance_ctrv")
    from edgeguard.device_policy import ForkliftLimit as _FL
    tags = {w: _FL("coop") for w in wp} if d2d and system == "edgeguard" else {}
    drng = random.Random(seed ^ 0xD2D)
    confirm = getattr(cfg, "plan_confirm", False) and system == "edgeguard"
    wanted, resend, crng = {}, [], random.Random(seed ^ 0xACC)
    states, pending, actual = {}, [], {k: 1e9 for k in nominal}
    last_hb = -1e9
    alarms = {"total": 0, "unneeded": 0}
    prox_in, prox_buzz = {}, {}
    key = (lambda other: other) if per_pair else (lambda other: "")
    for t in times:
        keep = []
        for due, ev, acts, to, other, *why in pending:
            if due > t:
                keep.append((due, ev, acts, to, other, *why))
                continue
            m = movers[to]
            if trace is not None and ev != "hb":
                trace.append({"t": round(t, 2), "type": "deliver", "ev": ev, "to": to, "about": other,
                              "acts": (acts.get(to) or {}), "reason": why[0] if why else None})
            ts = why[1] if len(why) > 1 and getattr(cfg, "msg_order", False) else None
            if ev == "hb":
                m.pending.append((t, "hb", None, ""))
                for w in tags:                         # the heartbeat on <ae>/control reaches the tags too
                    if drng.random() >= down_loss:
                        tags[w].on_heartbeat(t)
            elif m.kind == "forklift":
                fa = acts.get(to) or {}
                m.on_alert(t, ev, fa.get("speed_limit"), src=key(other), stop_at=fa.get("stop_at"), ts=ts)
            else:
                wa = acts.get(to) or {}
                m.on_alert(t, ev, wa.get("aside"), vibrate=wa.get("vibrate"), rng=rng, src=key(other), ts=ts)
                if to in tags:
                    tags[to].on_heartbeat(t)           # any MEC message proves it is alive
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
        if attentive:                          # the driver brakes for someone right in front of the truck
            for f in fp:
                mf = movers[f]
                if mf.human_cap and mf.human_cap[1] > t:
                    continue
                xf, yf = mf.pos()
                th, sign, _ = mf.path.meta_at(mf.s)
                hx, hy = math.cos(th) * sign, math.sin(th) * sign
                for w in wp:
                    xw, yw = movers[w].pos()
                    ahead, lat = (xw - xf) * hx + (yw - yf) * hy, abs(-(xw - xf) * hy + (yw - yf) * hx)
                    if 0 < ahead < 6.0 and lat < 1.2 and mf.v > 0.3:
                        mf.human_cap = (t + 1.0, t + 3.0, 0.0)          # perception-reaction 1.0 s, then stop
                        break
        if system != "edgeguard":              # local systems need no MEC heartbeat
            for f in fp:
                movers[f].fl.hb_t = t
            if system == "speed_zone":
                for f in fp:
                    movers[f].fl.limits["zone"] = (ZONE_KMH / 3.6, t)
            elif system.startswith("proximity"):
                for f in fp:
                    mf = movers[f]
                    for w in wp:
                        xw, yw = movers[w].pos()
                        xf, yf = mf.pos()
                        d = math.hypot(xw - xf, yw - yf) + rng.gauss(0, 0.1)        # UWB two-way ranging
                        zone = 2 if d < danger_m else 1 if d < warn_m else 0
                        was = prox_in.get((w, f), 0)
                        if zone == 0 and d > warn_m + 0.5:
                            mf.fl.limits.pop(w, None)
                            prox_in[(w, f)] = 0
                            continue
                        if zone:
                            prox_in[(w, f)] = max(zone, was) if zone == 2 else zone
                            mf.fl.limits[w] = (0.0 if zone == 2 else PROX_SLOW_MPS, t)
                            if was == 0 or t - prox_buzz.get((w, f), -1e9) >= 3.0:   # tag buzzes, again every 3 s inside
                                prox_buzz[(w, f)] = t
                                alarms["total"] += 1
                                alarms["unneeded"] += nominal[(w, f)] > UNNEEDED_M
                                movers[w].on_alert(t, "raise", vibrate=True, rng=rng, src=f)
        if tags:                               # D2D state broadcast and the local rule while MEC is silent
            st_f = {}
            for f in fp:
                mf = movers[f]
                smp = mf.sample()
                x, y = mf.pos()
                st_f[f] = (x + drng.gauss(0, noise), y + drng.gauss(0, noise),
                           smp["speed"] * math.cos(smp["heading"]), smp["speed"] * math.sin(smp["heading"]))
                mf.fl.on_own_state(t, *st_f[f])
            for w in wp:
                mw = movers[w]
                x, y = mw.pos()
                wv = 0.0 if (mw.stop_from <= t < mw.stop_until) or mw.blocked else mw.v
                (px, py) = mw.path.pos(min(mw.path.end, mw.s + 0.1))
                (qx, qy) = mw.path.pos(mw.s)
                un = math.hypot(px - qx, py - qy) or 1.0
                sw = (x + drng.gauss(0, noise), y + drng.gauss(0, noise),
                      wv * (px - qx) / un + drng.gauss(0, 0.1), wv * (py - qy) / un + drng.gauss(0, 0.1))
                tags[w].on_own_state(t, *sw)
                for f in fp:
                    xf, yf = movers[f].pos()
                    if math.hypot(x - xf, y - yf) > 25.0:
                        continue
                    if drng.random() >= 0.05:
                        movers[f].fl.on_peer_state(t, w, *sw)
                    if drng.random() >= 0.05:
                        tags[w].on_peer_state(t, f, *st_f[f])
                if tags[w].vibrate_local(t):
                    mw.on_alert(t, "local", vibrate=True)
                live = {k: u for k, u in mw.holds.items() if u > t}
                if live and t - mw.stop_from < 20.0 and tags[w].truck_near(t):   # WaitCue keep (HOLD_MAX_S)
                    for k, u in live.items():
                        if u < t + 0.2:
                            mw.holds[k] = t + 0.2
                    mw.stop_until = max(mw.stop_until, t + 0.2)
        for m in movers.values():
            m.step(t, DT)
        if trace is not None:
            from edgeguard.device_policy import SILENCE_S
            for f in fp:
                mf = movers[f]
                trace.append({"t": round(t, 2), "type": "fstep", "f": f, "v": round(mf.v, 3), "vn": round(mf.path.v_nom(mf.s), 3),
                              "lim": mf.fl.effective(t), "silent": t - mf.fl.hb_t > SILENCE_S,
                              "limits": {k: v for k, (v, _) in mf.fl.limits.items()},
                              "stops": sorted(mf.fl.stops)})
        pos = {k: m.pos() for k, m in movers.items()}
        for (w, f) in actual:
            d_wf = math.hypot(pos[w][0] - pos[f][0], pos[w][1] - pos[f][1])
            actual[(w, f)] = min(actual[(w, f)], d_wf)
            if trace is not None and d_wf < 8.0:
                mw, mf = movers[w], movers[f]
                trace.append({"t": round(t, 2), "type": "pair", "w": w, "f": f, "d": round(d_wf, 2),
                              "wv": round(mw.v, 2), "fv": round(mf.v, 2), "flim": mf.fl.effective(t),
                              "wstop": mw.stop_from <= t < mw.stop_until, "holds": sorted(mw.holds), "aside": mw.aside is not None,
                              "blocked": mw.blocked, "wpos": [round(v, 2) for v in pos[w]], "fpos": [round(v, 2) for v in pos[f]]})
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
        if t < 0.5 or system != "edgeguard":
            continue

        if mec_down and mec_down[0] <= t < mec_down[1]:
            states.clear()                     # restarted MEC app: no memory of the alerts it had sent
            continue                           # MEC app silent: no alerts, no heartbeats

        if wanted:                             # plan confirmation: the truck reports the plan it applies
            for (f, w), (ts, ev0, acts0, why0) in list(wanted.items()):
                if t - ts < cfg.ack_s:
                    continue
                fa, fl_ = acts0.get(f) or {}, movers[f].fl
                lim = fl_.limits.get(w)
                ok = ((ev0 == "clear" or fa.get("speed_limit") is None) and lim is None or
                      lim is not None and fa.get("speed_limit") is not None and abs(lim[0] - fa["speed_limit"]) < 0.01)
                stp = fl_.stops.get(w)
                ok = ok and ((ev0 == "clear" or fa.get("stop_at") is None) == (stp is None))
                if ok:
                    del wanted[(f, w)]
                elif crng.random() >= up_loss:     # its status got through and shows the old plan: send again
                    wanted[(f, w)] = (t, ev0, acts0, why0)
                    resend.append((ev0, acts0, f, w, why0))

        def send(ev, acts, to, other, reason=None):
            lost = rng.random() < down_loss
            if trace is not None and ev != "hb":
                trace.append({"t": round(t, 2), "type": "send", "ev": ev, "to": to, "about": other, "lost": lost,
                              "reason": reason})
            if not lost:
                pending.append((t + max(0.0, rng.gauss(lat_ms, jit_ms)) / 1000, ev, acts, to, other, reason, t))
            if confirm and to in fp and ev != "hb":
                wanted[(to, other)] = (t, ev, acts, reason)
        for ev0, acts0, f, w, why0 in resend:
            send(ev0, acts0, f, w, why0)
        resend.clear()
        if t - last_hb >= 1.0 - 1e-9:
            last_hb = t
            for f in fp:
                send("hb", {}, f, "")
        for r in engine.evaluate():
            st = states.setdefault((r.worker, r.forklift), AlertState())
            others = [tr for tr in engine.tracks.values() if tr.kind == "forklift" and tr.x is not None]
            ev, acts = decide(st, r, engine.tracks.get(r.worker), engine.tracks.get(r.forklift), cfg, t, others=others)
            if (ev == "raise" or ev == "aside" and (acts.get(r.worker) or {}).get("new")) \
                    and (acts.get(r.worker) or {}).get("vibrate"):
                alarms["total"] += 1
                alarms["unneeded"] += nominal[(r.worker, r.forklift)] > UNNEEDED_M
            if ev:
                send(ev, acts, r.worker, r.forklift, r.reason)
                if ev not in ("wait", "release", "aside"):
                    send(ev, acts, r.forklift, r.worker, r.reason)
    fl = [m for m in movers.values() if m.kind == "forklift"]
    wk = [m for m in movers.values() if m.kind == "worker"]
    nom = sum(_nominal_s(m.path) for m in fl)
    if trace is not None:
        trace.append({"type": "env", "lat_ms": round(lat_ms), "jit_ms": round(jit_ms), "up_loss": round(up_loss, 3),
                      "down_loss": round(down_loss, 3), "noise": round(noise, 3),
                      "collided": [list(k) for k in nominal if actual[k] < R_COLLIDE]})
    return {"conflicts": sum(d < R_CONTACT for d in nominal.values()),
            "collisions": sum(actual[k] < R_COLLIDE for k in nominal),
            "close_calls": sum(actual[k] < R_CONTACT for k in nominal),
            "collisions_in_conflict": sum(actual[k] < R_COLLIDE for k, d in nominal.items() if d < R_CONTACT),
            "forklift_m": sum(min(m.s, _nominal_s(m.path)) for m in fl), "forklift_nominal_m": nom,
            "forklift_lost_s": sum(m.lost_s for m in fl), "worker_wait_s": sum(m.wait_s for m in wk),
            "pairs_close": sum(d < 4.0 for d in nominal.values()),
            "alarms": alarms["total"], "alarms_unneeded": alarms["unneeded"],
            "near": sum(actual[k] < R_CONTACT for k in nominal),                   # closer than 1.5 m (incl. collisions)
            "shortfall_m": round(sum(max(0.0, R_CONTACT - actual[k]) for k in nominal), 3)}


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
