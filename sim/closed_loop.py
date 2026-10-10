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
from edgeguard.device_policy import ForkliftLimit
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
    f_link_down: tuple | None = None  # (t0, t1): forklift in a radio dead zone (no MEC up/down link)
    w_link_down: tuple | None = None  # (t0, t1): worker tag in a dead zone
    d2d_range_m: float = 40.0       # peer-to-peer broadcast (ESP-NOW / sidelink), coop mode
    d2d_loss: float = 0.10
    d2d_latency_s: float = 0.01
    d2d_relay_repeat: int = 3       # a relayed MEC message is broadcast this many times (cheap, 1 ms each)


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
    worker_wait_s: float = 0.0      # worker seconds lost to stops

    @property
    def collision(self):
        return self.actual_d_min < R_COLLIDE

    @property
    def timely(self):
        return self.first_alert is not None and self.t_contact is not None \
            and self.t_contact - self.first_alert >= LEAD_REQ


def _in_lane(worker, forklift, half_width=1.5):
    """Worker already within the forklift's lane (stopping there would not help)."""
    (xw, yw), (xf, yf) = worker.pos(), forklift.pos()
    hd, _, _ = forklift.path.meta_at(forklift.s)
    return abs(-(xw - xf) * math.sin(hd) + (yw - yf) * math.cos(hd)) < half_width


VISION_M = 12.0          # people notice each other within this range when nothing blocks the view
P_WORKER_SEES, P_DRIVER_SEES = 0.6, 0.7


ROUTE_SHARE = False   # forklifts send their planned route (next 10 m of waypoints) with each sample


def _route(forklift):
    p = forklift.path
    return [p.pos(min(p.end, forklift.s + d)) for d in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0)]


def run_episode(gen, rng: random.Random, cfg: RiskConfig, method="guidance_ctrv", net: Net = Net(),
                noise=0.15, react=True, map_aware=False, human_vision=False):
    """map_aware   : the risk engine knows the site map (edgeguard/sitemap.py) of the scenario
    human_vision: people yield on their own once they can see each other (line of sight clear,
                  within VISION_M, closing) - which is exactly what a blind corner takes away."""
    name, times, w, f = gen(rng)
    from edgeguard.sitemap import SiteMap
    from sim.scenarios import SCENARIO_MAPS
    world = SiteMap(SCENARIO_MAPS.get(name, []))
    seen, last_d = False, None
    worker = Mover("w", "worker", Path(w))
    forklift = Mover("f", "forklift", Path([(x, y) for x, y, *_ in f],
                                            [(th, 1 if sp >= 0 else -1, yw) for _, _, th, sp, yw in f]))
    engine = RiskEngine(cfg, method, sitemap=world if map_aware else None)
    st = AlertState()
    pending = []                                   # (deliver_at, event, actions, level, to)
    coop = forklift.fl.mode.startswith("coop")      # D2D state broadcast
    relay = forklift.fl.mode == "coop"              # ... and relay through a neighbour
    wl = ForkliftLimit(forklift.fl.mode)           # the worker tag's copy of the local rules

    def link_up(win, t):
        return win is None or not (win[0] <= t < win[1])

    def d2d_ok(t):                                 # one D2D frame between the two devices
        (ax, ay), (bx, by) = worker.pos(), forklift.pos()
        return coop and math.hypot(ax - bx, ay - by) <= net.d2d_range_m and rng.random() >= net.d2d_loss

    def route(t, to):
        """Delay added to a MEC message for device `to` ('f' / 'w'), or None if it cannot arrive."""
        own, other = (net.f_link_down, net.w_link_down) if to == "f" else (net.w_link_down, net.f_link_down)
        if link_up(own, t):
            return 0.0
        if relay and link_up(other, t) and any(d2d_ok(t) for _ in range(net.d2d_relay_repeat)):
            return net.d2d_latency_s                   # relayed by the neighbour that still hears MEC
        return None
    d_nom = [math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(w, f)]
    t_contact = next((k * DT for k, d in enumerate(d_nom) if d < R_CONTACT), None)
    first_alert, alerts, actual_min = None, 0, 1e9
    last_hb, restarted = -1e9, True
    for k, t in enumerate(times):
        # deliver alerts that have arrived
        keep = []
        for due, ev, acts, lvl, to in pending:
            if due > t:
                keep.append((due, ev, acts, lvl, to))
                continue
            if ev == "hb":
                if to == "f":
                    forklift.pending.append((t, "hb", None, ""))
                else:
                    wl.on_heartbeat(t)
                continue
            if ev in ("raise", "refresh") and first_alert is None:
                first_alert = due
            if to == "w":
                wl.on_heartbeat(t)
            if react:
                if to == "f":
                    forklift.on_alert(t, ev, acts.get("f", {}).get("speed_limit"), src="w")
                else:
                    wa = acts.get("w", {})
                    worker.on_alert(t, ev, wa.get("aside"), vibrate=wa.get("vibrate"), rng=rng, src="f")
        pending = keep
        worker.step(t, DT)
        forklift.step(t, DT)
        (xw, yw), (xf, yf) = worker.pos(), forklift.pos()
        actual_min = min(actual_min, math.hypot(xw - xf, yw - yf))
        if human_vision and not seen:
            d_now = math.hypot(xw - xf, yw - yf)
            closing = last_d is not None and d_now < last_d - 1e-3
            last_d = d_now
            if closing and d_now < VISION_M and not world.blocked((xw, yw), (xf, yf)):
                seen = True
                if rng.random() < P_WORKER_SEES and not _in_lane(worker, forklift):
                    worker.on_alert(t, "local", vibrate=True)            # stops after 0.8 s, for 2 s
                if rng.random() < P_DRIVER_SEES:
                    forklift.human_cap = (t + 0.8, t + 3.8, 1.0)      # slows to 1 m/s for 3 s
        # direct UWB ranging forklift <-> worker tag (used only by the local-fallback modes)
        d_true = math.hypot(xw - xf, yw - yf)
        every = max(1, round(1.0 / (net.uwb_peer_hz * DT)))
        if k % every == 0 and d_true <= net.uwb_peer_range_m and rng.random() >= net.uwb_peer_drop:
            rr = max(0.0, d_true + net.uwb_peer_bias + rng.gauss(0, net.uwb_peer_sigma))
            forklift.fl.on_range(t, "w", rr)
            wl.on_range(t, "f", rr)                      # two-way ranging: both ends know it
        if coop:                                         # D2D state broadcast (10 Hz, both ways)
            wv = worker.v if not (worker.stop_from <= t < worker.stop_until) else 0.0
            sw = forklift.sample()
            fvx, fvy = sw["speed"] * math.cos(sw["heading"]), sw["speed"] * math.sin(sw["heading"])
            (px, py) = worker.path.pos(min(worker.path.end, worker.s + 0.1))
            ux, uy = (px - xw + worker.offset[0], py - yw + worker.offset[1])
            un = math.hypot(ux, uy) or 1.0
            wvx, wvy = wv * ux / un, wv * uy / un
            nz = lambda: rng.gauss(0, noise)             # noqa: E731  (UWB fix noise)
            fw = (xw + nz(), yw + nz(), wvx + rng.gauss(0, 0.1), wvy + rng.gauss(0, 0.1))
            ff = (xf + nz(), yf + nz(), fvx + rng.gauss(0, 0.05), fvy + rng.gauss(0, 0.05))
            forklift.fl.on_own_state(t, *ff)
            wl.on_own_state(t, *fw)
            if d2d_ok(t):
                forklift.fl.on_peer_state(t, "w", *fw)
            if d2d_ok(t):
                wl.on_peer_state(t, "f", *ff)
        if react and (forklift.fl.mode.endswith("_tag") or coop):
            if wl.vibrate_local(t):                     # the tag's own copy of the rules
                worker.on_alert(t, "local", vibrate=True)
        # sensors (a device in a dead zone reaches the MEC app only through a D2D relay)
        if rng.random() >= net.up_loss and route(t, "w") is not None:
            engine.update(Track, "w", "worker", t, x=xw + rng.gauss(0, noise), y=yw + rng.gauss(0, noise))
        if rng.random() >= net.up_loss and route(t, "f") is not None:
            smp = forklift.sample()
            engine.update(Track, "f", "forklift", t, x=xf + rng.gauss(0, noise), y=yf + rng.gauss(0, noise),
                          speed=smp["speed"] + rng.gauss(0, 0.05), heading=smp["heading"] + rng.gauss(0, 0.035),
                          yaw_rate=smp["yaw_rate"] + rng.gauss(0, 0.03),
                          route=_route(forklift) if ROUTE_SHARE else None)
        if t < 0.5:
            continue
        down = net.mec_down is not None and net.mec_down[0] <= t < net.mec_down[1]
        if down:
            restarted = False
            continue
        if net.mec_down is not None and t >= net.mec_down[1] and not restarted:
            restarted = True                                   # fresh process: no tracks, no alert state
            engine, st = RiskEngine(cfg, method, sitemap=world if map_aware else None), AlertState()
        if t - last_hb >= net.heartbeat_s - 1e-9:
            last_hb = t
            for to in ("f", "w"):
                extra = route(t, to)
                if extra is not None and rng.random() >= net.down_loss:
                    pending.append((t + extra + max(0.0, rng.gauss(net.latency_ms, net.jitter_ms)) / 1000,
                                    "hb", {}, 0, to))
        for r in engine.evaluate():
            ev, acts = decide(st, r, engine.tracks.get("w"), engine.tracks.get("f"), cfg, t)
            if ev:
                alerts += 1
                for to in (("w",) if ev in ("release", "wait", "aside") else ("f", "w")):
                    extra = route(t, to)
                    if extra is not None and rng.random() >= net.down_loss:
                        lat = max(0.0, rng.gauss(net.latency_ms, net.jitter_ms)) / 1000
                        pending.append((t + extra + lat, ev, acts, r.level, to))
    T = times[-1]
    return EpisodeResult(name, t_contact is not None, t_contact, first_alert, min(d_nom), actual_min,
                         min(forklift.path.end, _nominal_s(forklift.path, T)),
                         forklift.s, forklift.lost_s, worker.stops, alerts, worker.wait_s)


def _nominal_s(path, T):
    """Arc length the forklift would have covered by time T without slow-downs."""
    s, t = 0.0, 0.0
    while t < T and s < path.end:
        s += path.v_nom(s) * DT
        t += DT
    return s


# ----------------------------------------------------------------------------- metrics
def score(results, beta=2.0, collision_penalty=20.0, w_time=1.0, w_fp=0.5, w_worker=0.0):
    """Training reward and evaluation metrics for a batch of episodes.

    Reward per episode (what the optimiser maximises):
        r = - C * collision - w_time * forklift_seconds_lost - w_worker * worker_seconds_lost
            - w_fp * false_alarm
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
    reward = -sum(collision_penalty * r.collision + w_time * r.lost_s + w_worker * r.worker_wait_s
                  + w_fp * (1 if (not r.conflict and r.first_alert is not None) else 0)
                  for r in results) / len(results)
    return {"reward": reward, "precision": p, "recall": rc, "f_beta": fb, "beta": beta,
            "throughput": thr, "collisions": coll, "conflicts": len(conf), "episodes": len(results),
            "false_alarms": fp, "lost_s_mean": sum(r.lost_s for r in results) / len(results),
            "worker_wait_s_mean": sum(r.worker_wait_s for r in results) / len(results)}
