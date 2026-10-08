"""Fast in-process closed-loop simulator for policy training.

Same pieces as the real-time online simulation (sim/online_sim.py) - tracker,
risk engine, alert policy (edgeguard/alerting.py), reacting forklift and worker -
but stepped in simulated time with a network model instead of real HTTP, so
thousands of encounters run in minutes.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from edgeguard.alerting import AlertState, decide
from edgeguard.risk import RiskConfig, RiskEngine
from edgeguard.tracking import Track
from sim import scenarios
from sim.online_sim import Mover, Path, R_COLLIDE, R_CONTACT

DT = scenarios.DT
LEAD_REQ = 1.0


@dataclass
class Net:
    latency_ms: float = 75.0      # sensor -> CSE -> MEC -> CSE -> device (online sim p50 ~ 70 ms)
    jitter_ms: float = 20.0
    up_loss: float = 0.0
    down_loss: float = 0.0
    mec_down: tuple | None = None   # (t_start, t_end): MEC app dead, restarts with empty state
    heartbeat_s: float = 1.0        # <ae>/control heartbeat (edgeguard/device_policy.py)
    uwb_peer_range_m: float = 30.0  # direct forklift <-> tag ranging (local fallback modes)
    uwb_peer_sigma: float = 0.10
    uwb_peer_drop: float = 0.10     # missed ranging rounds (NLOS, collisions)
    uwb_peer_hz: float = 10.0       # ranging rounds per second (arduino-dw1000 ~80 ms cycle)
    uwb_peer_bias: float = 0.0      # NLOS adds path length: ranges read long by this (m)


@dataclass
class EpisodeResult:
    scenario: str
    conflict: bool
    t_contact: float | None
    first_alert: float | None       # when the first alert reached the devices
    nominal_d_min: float
    actual_d_min: float
    forklift_nominal_m: float       # distance the forklift would have driven
    forklift_actual_m: float
    lost_s: float
    worker_stops: int
    alerts: int

    @property
    def collision(self):
        return self.actual_d_min < R_COLLIDE

    @property
    def timely(self):
        return self.first_alert is not None and self.t_contact is not None \
            and self.t_contact - self.first_alert >= LEAD_REQ


def run_episode(gen, rng: random.Random, cfg: RiskConfig, method="guidance_ctrv", net: Net = Net(),
                noise=0.15, react=True):
    name, times, w, f = gen(rng)
    worker = Mover("w", "worker", Path(w))
    forklift = Mover("f", "forklift", Path([(x, y) for x, y, *_ in f],
                                            [(th, 1 if sp >= 0 else -1, yw) for _, _, th, sp, yw in f]))
    engine = RiskEngine(cfg, method)
    st = AlertState()
    pending = []                                   # (deliver_at, event, actions)
    d_nom = [math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(w, f)]
    t_contact = next((k * DT for k, d in enumerate(d_nom) if d < R_CONTACT), None)
    first_alert, alerts, actual_min = None, 0, 1e9
    last_hb, restarted = -1e9, True
    for k, t in enumerate(times):
        # deliver alerts that have arrived
        keep = []
        for due, ev, acts, lvl in pending:
            if due > t:
                keep.append((due, ev, acts, lvl))
                continue
            if ev == "hb":
                forklift.pending.append((t, "hb", None))
                continue
            if ev in ("raise", "refresh") and first_alert is None:
                first_alert = due
            if react:
                fa = acts.get("f", {})
                forklift.on_alert(t, ev, fa.get("speed_limit"))
                worker.on_alert(t, ev, vibrate=acts.get("w", {}).get("vibrate"))
        pending = keep
        worker.step(t, DT)
        forklift.step(t, DT)
        (xw, yw), (xf, yf) = worker.path.pos(worker.s), forklift.path.pos(forklift.s)
        actual_min = min(actual_min, math.hypot(xw - xf, yw - yf))
        # direct UWB ranging forklift <-> worker tag (used only by the local-fallback modes)
        d_true = math.hypot(xw - xf, yw - yf)
        every = max(1, round(1.0 / (net.uwb_peer_hz * DT)))
        if k % every == 0 and d_true <= net.uwb_peer_range_m and rng.random() >= net.uwb_peer_drop:
            forklift.fl.on_range(t, "w", max(0.0, d_true + net.uwb_peer_bias
                                             + rng.gauss(0, net.uwb_peer_sigma)))
        if react and forklift.fl.mode.endswith("_tag") and forklift.fl.vibrate_local(t):
            worker.on_alert(t, "raise", vibrate=True)    # the tag sees the same two-way range
        # sensors
        if rng.random() >= net.up_loss:
            engine.update(Track, "w", "worker", t, x=xw + rng.gauss(0, noise), y=yw + rng.gauss(0, noise))
        if rng.random() >= net.up_loss:
            smp = forklift.sample()
            engine.update(Track, "f", "forklift", t, x=xf + rng.gauss(0, noise), y=yf + rng.gauss(0, noise),
                          speed=smp["speed"] + rng.gauss(0, 0.05), heading=smp["heading"] + rng.gauss(0, 0.035),
                          yaw_rate=smp["yaw_rate"] + rng.gauss(0, 0.03))
        if t < 0.5:
            continue
        down = net.mec_down is not None and net.mec_down[0] <= t < net.mec_down[1]
        if down:
            restarted = False
            continue
        if net.mec_down is not None and t >= net.mec_down[1] and not restarted:
            restarted = True                                   # fresh process: no tracks, no alert state
            engine, st = RiskEngine(cfg, method), AlertState()
        if t - last_hb >= net.heartbeat_s - 1e-9:
            last_hb = t
            if rng.random() >= net.down_loss:
                pending.append((t + max(0.0, rng.gauss(net.latency_ms, net.jitter_ms)) / 1000, "hb", {}, 0))
        for r in engine.evaluate():
            ev, acts = decide(st, r, engine.tracks.get("w"), engine.tracks.get("f"), cfg, t)
            if ev:
                alerts += 1
                if rng.random() >= net.down_loss:
                    lat = max(0.0, rng.gauss(net.latency_ms, net.jitter_ms)) / 1000
                    pending.append((t + lat, ev, acts, r.level))
    T = times[-1]
    return EpisodeResult(name, t_contact is not None, t_contact, first_alert, min(d_nom), actual_min,
                         min(forklift.path.end, _nominal_s(forklift.path, T)),
                         forklift.s, forklift.lost_s, worker.stops, alerts)


def _nominal_s(path, T):
    """Arc length the forklift would have covered by time T without slow-downs."""
    s, t = 0.0, 0.0
    while t < T and s < path.end:
        s += path.v_nom(s) * DT
        t += DT
    return s


# ----------------------------------------------------------------------------- metrics
def score(results, beta=2.0, collision_penalty=20.0, w_time=1.0, w_fp=0.5):
    """Training reward and evaluation metrics for a batch of episodes.

    Reward per episode (what the optimiser maximises):
        r = - C * collision - w_time * forklift_seconds_lost - w_fp * false_alarm
    Evaluation (what we select by):
        precision = TP / (TP + FP)       alarms that were real conflicts
        recall    = TP / (TP + FN)       real conflicts warned >= 1 s ahead
        F_beta    = (1 + b^2) P R / (b^2 P + R)     b > 1 weights recall (safety) higher
        throughput = forklift distance driven / distance without any slow-down
    """
    conf = [r for r in results if r.conflict]
    nonc = [r for r in results if not r.conflict]
    tp = sum(r.timely for r in conf)
    fn = len(conf) - tp
    fp = sum(1 for r in nonc if r.first_alert is not None)
    p = tp / (tp + fp) if tp + fp else 1.0
    rc = tp / (tp + fn) if tp + fn else 1.0
    fb = (1 + beta ** 2) * p * rc / (beta ** 2 * p + rc) if p + rc else 0.0
    nom = sum(r.forklift_nominal_m for r in results)
    act = sum(min(r.forklift_actual_m, r.forklift_nominal_m) for r in results)
    thr = act / nom if nom else 1.0
    coll = sum(r.collision for r in results)
    reward = -sum(collision_penalty * r.collision + w_time * r.lost_s
                  + w_fp * (1 if (not r.conflict and r.first_alert is not None) else 0)
                  for r in results) / len(results)
    return {"reward": reward, "precision": p, "recall": rc, "f_beta": fb, "beta": beta,
            "throughput": thr, "collisions": coll, "conflicts": len(conf), "episodes": len(results),
            "false_alarms": fp, "lost_s_mean": sum(r.lost_s for r in results) / len(results)}
