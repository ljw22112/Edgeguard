"""Closed-loop online simulation of a whole site, through the real EdgeGuard stack.

Replaces the planned RC-car field test.  Virtual workers and forklifts publish
to the CSE exactly like the devices, the MEC app predicts and alerts, and the
virtual devices *react*: a forklift brakes to the commanded speed, a worker
stops when the tag vibrates.  Faults are injected on the way: sensor noise,
uplink / downlink loss, network latency and jitter, clock skew, low sample
rate, UWB shadowing, odd behaviours and crowded aisles.

    python -m sim.online_sim --cases all --out results/online_sim.json
    python -m sim.online_sim --cases baseline uplink_loss_30

Prerequisite: a CSE (Mobius by default, see --cse) is running; this tool starts
and stops the MEC app itself.
"""
from __future__ import annotations

import argparse
import bisect
import copy
import json
import math
import os
import queue
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from edgeguard.device_policy import ForkliftLimit, ReportRate      # noqa: E402
from edgeguard.onem2m import OneM2MClient, parse_notification       # noqa: E402
from sim import scenarios                                            # noqa: E402

DT = scenarios.DT
T_ROUND = 12.0
R_CONTACT = 1.5        # centre distance treated as contact (same as the offline evaluation)
R_COLLIDE = 1.0        # bodies touching
LEAD_REQ = 1.0

BASE_CASE = dict(pairs=8, rounds=3, layout="spaced", mix="standard", noise=0.15, rate_hz=10,
                 up_loss=0.0, down_loss=0.0, delay_ms=0.0, jitter_ms=0.0, skew_ms=0.0,
                 dropout=False, method="guidance_ctrv", react=True,
                 restart_at=None, background=0, adaptive=False)
CASES = {
    "baseline":        {},
    "noise_high":      dict(noise=0.35),
    "uplink_loss_10":  dict(up_loss=0.10),
    "uplink_loss_30":  dict(up_loss=0.30),
    "downlink_loss_20": dict(down_loss=0.20),
    "wifi_latency":    dict(delay_ms=60, jitter_ms=30),
    "rate_5hz":        dict(rate_hz=5),
    "clock_skew":      dict(skew_ms=300),
    "uwb_shadow":      dict(dropout=True),
    "odd_behaviour":   dict(mix="extra"),
    "crowded_aisle":   dict(layout="dense", pairs=6),
    "worst_combined":  dict(noise=0.3, up_loss=0.2, down_loss=0.1, delay_ms=60, jitter_ms=30,
                            skew_ms=200, dropout=True),
    "proximity_5m":    dict(method="distance"),
    "baseline_adaptive": dict(adaptive=True),                    # regression check at normal load
    "scale_12":        dict(pairs=12, rounds=2),                 # 24 devices, 240 samples/s (design load)
    "scale_20":        dict(pairs=20, rounds=2),                 # 40 devices, 400 samples/s
    # 40 devices, 10 pairs meet and 10 pairs work apart (as on a real site), without / with
    # adaptive reporting (far devices at 2 Hz, edgeguard/rate_control.py)
    "scale_20_sparse":   dict(pairs=20, background=10, rounds=3),
    "scale_20_adaptive": dict(pairs=20, background=10, rounds=3, adaptive=True),
    "mec_restart":     dict(restart_at=4.0, adaptive=True, background=3),   # MEC app killed + restarted mid-round
}


# ---------------------------------------------------------------------------------------
class Path:
    """Nominal trajectory, re-parameterised by arc length so it can be slowed down."""

    def __init__(self, pts, meta=None):
        self.pts = pts
        self.meta = meta                                     # forklift: (heading, sign, yaw)
        self.s = [0.0]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            self.s.append(self.s[-1] + math.hypot(x1 - x0, y1 - y0))
        self.end = self.s[-1]

    def _idx(self, s):
        return max(0, min(len(self.s) - 2, bisect.bisect_right(self.s, s) - 1))

    def pos(self, s):
        if s >= self.end:
            return self.pts[-1]
        i = self._idx(s)
        seg = self.s[i + 1] - self.s[i]
        a = 0.0 if seg < 1e-9 else (s - self.s[i]) / seg
        (x0, y0), (x1, y1) = self.pts[i], self.pts[i + 1]
        return (x0 + a * (x1 - x0), y0 + a * (y1 - y0))

    def v_nom(self, s):
        if s >= self.end - 1e-6:
            return 0.0
        i = self._idx(s)
        return (self.s[i + 1] - self.s[i]) / DT

    def meta_at(self, s):
        return self.meta[self._idx(s)] if self.meta else None


class Mover:
    def __init__(self, oid, kind, path):
        self.id, self.kind, self.path = oid, kind, path
        self.s, self.v = 0.0, path.v_nom(0.0)
        self.fl = ForkliftLimit()                    # forklift speed limit with silence fail-safe
        self.pending = []                            # (apply_at, scale)
        self.stop_from = self.stop_until = -1.0      # worker reaction window
        self.lost_s = 0.0                            # forklift seconds lost to slow-downs
        self.human_cap = None                        # (from, until, m/s): the driver slows on his own
        self.stops = 0

    def on_alert(self, t, event, limit=None, vibrate=False):
        if self.kind == "forklift":                       # limit: absolute m/s, None = no limit
            self.pending.append((t + 0.2, event, limit))                         # actuator delay
        elif vibrate and t > self.stop_until:
            self.stop_from, self.stop_until = t + 0.8, t + 2.8                   # reaction 0.8 s, stop 2 s
            self.stops += 1

    def step(self, t, dt):
        vn = self.path.v_nom(self.s)
        if self.kind == "forklift":
            ready = sorted((x for x in self.pending if x[0] <= t), key=lambda x: x[0])
            if ready:
                self.pending = [x for x in self.pending if x[0] > t]
            for _, ev, lim in ready:
                if ev == "hb":
                    self.fl.on_heartbeat(t)
                else:
                    self.fl.on_alert(t, ev, lim)
            lim = self.fl.effective(t)
            target = vn if lim is None else min(vn, lim)
            if self.human_cap and self.human_cap[0] <= t < self.human_cap[1]:
                target = min(target, self.human_cap[2])
            dec, acc = 2.5, 1.0
            if vn > 0.1:
                self.lost_s += (1 - min(1.0, self.v / vn)) * dt
        else:
            target = 0.0 if self.stop_from <= t < self.stop_until else vn
            dec, acc = 2.0, 1.5
        if target < self.v:
            self.v = max(target, self.v - dec * dt)
        else:
            self.v = min(target, self.v + acc * dt)
        self.s += self.v * dt

    def sample(self):
        x, y = self.path.pos(self.s)
        if self.kind == "worker":
            return {"x": x, "y": y}
        heading, sign, yaw = self.path.meta_at(self.s)
        return {"x": x, "y": y, "speed": sign * self.v, "heading": heading,
                "yaw_rate": yaw if self.v > 0.05 else 0.0}


# ---------------------------------------------------------------------------------------
class Publisher(threading.Thread):
    """Per-device uplink with loss, latency and jitter (order preserved).

    Like the firmware (which publishes the *current* position every tick), a sample that is
    already superseded by a newer due sample when the uplink becomes free is skipped instead
    of queueing behind a slow CSE."""

    def __init__(self, client, path, case, rng):
        super().__init__(daemon=True)
        self.c, self.path, self.case, self.rng = client, path, case, rng
        self.q: queue.Queue = queue.Queue()
        self.last_due = 0.0
        self.sent = self.dropped = self.failed = self.skipped = 0

    def push(self, payload):
        if self.rng.random() < self.case["up_loss"]:
            self.dropped += 1
            return
        d = max(0.0, self.rng.gauss(self.case["delay_ms"], self.case["jitter_ms"])) / 1000
        due = max(time.time() + d, self.last_due)
        self.last_due = due
        self.q.put((due, payload))

    def run(self):
        while True:
            due, payload = self.q.get()
            if payload is None:
                return
            w = due - time.time()
            if w > 0:
                time.sleep(w)
            nxt = self.q.queue[0] if self.q.qsize() else None
            if nxt is not None and nxt[1] is not None and nxt[0] <= time.time():
                self.skipped += 1                       # newer sample ready: send that one
                continue
            try:
                self.c.create_cin(self.path, payload)
                self.sent += 1
            except Exception:
                self.failed += 1


class AlertSink:
    """One HTTP endpoint for all virtual devices; applies downlink loss / delay."""

    def __init__(self, port):
        self.handler = None
        sink = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.send_header("X-M2M-RSC", "2000")
                self.end_headers()
                try:
                    kind, a = parse_notification(json.loads(body))
                except ValueError:
                    return
                if kind == "cin" and isinstance(a, dict) and sink.handler:
                    sink.handler(a, time.time())

            def log_message(self, *x):
                pass
        self.srv = ThreadingHTTPServer(("0.0.0.0", port), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


# ---------------------------------------------------------------------------------------
def build_round(case, rng):
    gens = scenarios.GENERATORS if case["mix"] == "standard" else scenarios.EXTRA_GENERATORS
    pairs = []
    for i in range(case["pairs"]):
        name, times, w, f = rng.choice(gens)(rng)
        if case["layout"] == "spaced":
            ox, oy = (i % 4) * 60.0, (i // 4) * 60.0         # far apart: one encounter per pair
        else:
            ox, oy = rng.uniform(0, 14), rng.uniform(0, 14)  # crowded: everyone meets everyone
            if rng.random() < 0.5:                            # rotate some encounters 90 degrees
                w = [(-y, x) for x, y in w]
                f = [(-y, x, th + math.pi / 2, sp, yw) for x, y, th, sp, yw in f]
        fx_off = 35.0 if i >= case["pairs"] - case["background"] else 0.0   # works elsewhere
        w = [(x + ox, y + oy) for x, y in w]
        f = [(x + ox + fx_off, y + oy, th, sp, yw) for x, y, th, sp, yw in f]
        drop = None
        if case["dropout"]:
            st = rng.uniform(2.0, 5.0)
            drop = (st, st + 3.0)
        pairs.append({"name": name, "w": w, "f": f, "drop": drop})
    return pairs


def nominal_gt(wpts, fpts):
    d = [math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(wpts, fpts)]
    contact = next((k * DT for k, x in enumerate(d) if x < R_CONTACT), None)
    return {"d_min": min(d), "t_contact": contact}


POLICY = {}          # risk-parameter overrides (--policy)


def write_cfg(case, cse):
    base = yaml.safe_load(open(os.path.join(ROOT, "config", "site.yaml")))
    c = copy.deepcopy(base)
    c.setdefault("risk", {}).update(POLICY)
    c["cse"] = dict(cse)
    n = case["pairs"]
    c["devices"] = {"workers": [f"w{i:02d}" for i in range(n)],
                    "forklifts": [f"f{i:02d}" for i in range(n)], "cameras": []}
    c["mec"]["method"] = case["method"]
    c["mec"]["notify_url"] = "http://127.0.0.1:9090/notify"
    c["device_sim"]["notify_url"] = "http://127.0.0.1:9091/alert"
    c["cloud_sync"]["enabled"] = False
    c["mec_services"]["enabled"] = False
    c["security"]["enabled"] = False
    c["rate_control"] = {"enabled": bool(case["adaptive"])}
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="eg_online_")
    with os.fdopen(fd, "w") as fh:
        yaml.safe_dump(c, fh)
    return path, c


def run_case(name, case, cse, sink, seed, scen_seed=None):
    rng = random.Random(seed)
    scen_rng = random.Random((seed if scen_seed is None else scen_seed) * 7919)       # encounters only: identical across cases with the same seed
    cfg_path, cfg = write_cfg(case, cse)
    env = dict(os.environ, EDGEGUARD_CONFIG=cfg_path, MEC_LOG=f"/tmp/eg_online_{name}.log")
    subprocess.run(["bash", "scripts/mec.sh", "restart"], cwd=ROOT, env=env,
                   stdout=subprocess.DEVNULL, check=True)
    subprocess.run([sys.executable, "tools/setup_resources.py", "--config", cfg_path, "--reset"],
                   cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    ae = cfg["ae"]
    combos, latencies, pubs_all = [], [], []
    forklift_lost, worker_stops, episodes = [], 0, 0
    restarts = []

    for rnd in range(case["rounds"]):
        pairs = build_round(case, scen_rng)
        movers, pubs, skew = {}, {}, {}
        for i, pr in enumerate(pairs):
            wid, fid = f"w{i:02d}", f"f{i:02d}"
            movers[wid] = Mover(wid, "worker", Path(pr["w"]))
            movers[fid] = Mover(fid, "forklift", Path([(x, y) for x, y, *_ in pr["f"]],
                                                     [(th, 1 if sp >= 0 else -1, yw) for _, _, th, sp, yw in pr["f"]]))
            for oid, leaf in ((wid, "location"), (fid, "motion")):
                cl = OneM2MClient(cse["base_url"], cse["cse_rn"], cse["origin"], cse["rvi"], timeout=3)
                pubs[oid] = Publisher(cl, f"{ae}/{oid}/{leaf}", case, random.Random(rng.random()))
                pubs[oid].start()
                skew[oid] = rng.uniform(-case["skew_ms"], case["skew_ms"])
        dev_rate = {oid: ReportRate() for oid in movers}      # commanded rate with fail-safe
        # nominal ground truth for every worker x forklift combination that actually meets
        gt = {}
        for i, pi in enumerate(pairs):
            for j, pj in enumerate(pairs):
                g = nominal_gt(pi["w"], [(x, y) for x, y, *_ in pj["f"]])
                if g["d_min"] < 8.0:
                    gt[(f"w{i:02d}", f"f{j:02d}")] = g
        first_alert = {}
        alert_log = {}
        actual_min = {k: 1e9 for k in gt}
        t0 = time.time()
        lock = threading.Lock()

        def on_alert(a, now):
            if rng.random() < case["down_loss"]:
                return
            delay = max(0.0, rng.gauss(case["delay_ms"], case["jitter_ms"])) / 1000

            def apply():
                t = time.time() - t0
                if "rates" in a or a.get("hb"):                   # control: rate command / heartbeat
                    with lock:
                        for oid, hz in (a.get("rates") or {}).items():
                            if oid in dev_rate:
                                dev_rate[oid].on_command(t, hz)
                        for m in movers.values():
                            if m.kind == "forklift":
                                m.pending.append((t, "hb", None))
                    return
                w, f = a.get("worker"), a.get("forklift")
                acts = a.get("actions", {})
                with lock:
                    if a.get("event") in ("raise", "refresh") and (w, f) not in first_alert:
                        first_alert[(w, f)] = t
                    alert_log.setdefault((w, f), []).append(
                        (round(t, 2), a.get("event"), a.get("level"), acts.get(f, {}).get("speed_limit")))
                    if case["react"]:
                        for m in movers.values():               # any MEC message = heartbeat
                            if m.kind == "forklift" and m.id != f:
                                m.pending.append((t, "hb", None))
                        if f in movers:
                            fa = acts.get(f, {})
                            lim = fa.get("speed_limit")
                            if lim is None and a["event"] != "clear":      # older MEC app: ratio only
                                lim = fa.get("speed_scale", 1.0) * movers[f].v
                            movers[f].on_alert(t, a["event"], lim)
                        if w in movers:
                            movers[w].on_alert(t, a["event"], vibrate=acts.get(w, {}).get("vibrate"))
                if a.get("src_ts") and case["skew_ms"] == 0 and a.get("event") != "clear":
                    latencies.append(time.time() * 1000 - a["src_ts"])
            threading.Timer(delay, apply).start() if delay > 0 else apply()
        sink.handler = on_alert

        every = max(1, int(round(10 / case["rate_hz"])))
        k = 0
        restarted = False

        def do_restart(t_kill):
            r0 = time.time()
            subprocess.run(["bash", "scripts/mec.sh", "restart"], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL)
            restarts.append({"round": rnd, "t_kill": round(t_kill, 2),
                             "down_s": round(time.time() - r0, 2), "t_up": round(time.time() - t0, 2)})
        while True:
            t = time.time() - t0
            if t > T_ROUND:
                break
            if case["restart_at"] is not None and not restarted and t >= case["restart_at"]:
                restarted = True
                threading.Thread(target=do_restart, args=(t,), daemon=True).start()
            with lock:
                for m in movers.values():
                    m.step(t, DT)
                for (w, f) in gt:
                    (xw, yw), (xf, yf) = movers[w].path.pos(movers[w].s), movers[f].path.pos(movers[f].s)
                    actual_min[(w, f)] = min(actual_min[(w, f)], math.hypot(xw - xf, yw - yf))
                now_ms = int(time.time() * 1000)
                for i, pr in enumerate(pairs):
                    for oid in (f"w{i:02d}", f"f{i:02d}"):
                        ev = max(every, int(round(10 / dev_rate[oid].current(t))))
                        if (k % every if ev == every else (k + i) % ev) != 0:
                            continue
                        m = movers[oid]
                        smp = m.sample()
                        if oid.startswith("w") and pr["drop"] and pr["drop"][0] <= t < pr["drop"][1]:
                            continue                                    # tag shadowed
                        sx = smp["x"] + rng.gauss(0, case["noise"])
                        sy = smp["y"] + rng.gauss(0, case["noise"])
                        payload = {"id": oid, "kind": "worker" if oid[0] == "w" else "forklift",
                                   "ts": now_ms + int(skew[oid]), "x": round(sx, 3), "y": round(sy, 3)}
                        if oid[0] == "f":
                            payload.update(speed=round(smp["speed"] + rng.gauss(0, 0.05), 3),
                                           heading=round(smp["heading"] + rng.gauss(0, 0.035), 4),
                                           yaw_rate=round(smp["yaw_rate"] + rng.gauss(0, 0.03), 4))
                        pubs[oid].push(payload)
            k += 1
            time.sleep(max(0.0, t0 + k * DT - time.time()))
        sink.handler = None
        for p in pubs.values():
            p.q.put((0, None))
        pubs_all.extend(pubs.values())
        for key, g in gt.items():
            same = key[0][1:] == key[1][1:]
            combos.append({"round": rnd, "worker": key[0], "forklift": key[1],
                           "scenario": pairs[int(key[0][1:])]["name"] if same else "cross-pair",
                           "alerts": alert_log.get(key, [])[:8],
                           "nominal_d_min": round(g["d_min"], 2), "t_contact": g["t_contact"],
                           "actual_d_min": round(actual_min[key], 2),
                           "first_alert_t": first_alert.get(key)})
        forklift_lost += [m.lost_s for m in movers.values() if m.kind == "forklift"]
        worker_stops += sum(m.stops for m in movers.values() if m.kind == "worker")
        episodes += len(pairs)
        time.sleep(2.6)                                              # tracks go stale between rounds
    os.unlink(cfg_path)
    r = summarize(name, case, combos, latencies, forklift_lost, worker_stops, episodes, pubs_all)
    if restarts:
        r["restarts"] = restarts
        r["alerts_after_restart"] = sum(1 for c in r["combos"] for a in c["alerts"]
                                        if a[0] > restarts[c["round"]]["t_up"])
    return r


SPAWN_S = 2.5   # encounters that would collide this soon after a round starts are excluded:
                # the agents were placed already in conflict and nothing can warn 1 s ahead


def summarize(name, case, combos, latencies, lost, stops, episodes, pubs):
    spawned = [c for c in combos if c["t_contact"] is not None and c["t_contact"] < SPAWN_S]
    combos = [c for c in combos if c not in spawned]
    conf = [c for c in combos if c["t_contact"] is not None]
    nonc = [c for c in combos if c["t_contact"] is None]
    leads = [c["t_contact"] - c["first_alert_t"] for c in conf if c["first_alert_t"] is not None]
    timely = sum(1 for c in conf if c["first_alert_t"] is not None
                 and c["t_contact"] - c["first_alert_t"] >= LEAD_REQ)
    nom_coll = sum(1 for c in combos if c["nominal_d_min"] < R_COLLIDE)
    act_coll = sum(1 for c in combos if c["actual_d_min"] < R_COLLIDE)
    act_contact = sum(1 for c in combos if c["actual_d_min"] < R_CONTACT)
    lat = sorted(latencies)
    sent = sum(p.sent for p in pubs)
    return {
        "case": name, "params": {k: v for k, v in case.items() if BASE_CASE.get(k) != v},
        "episodes": episodes, "encounters": len(combos), "conflicts": len(conf),
        "excluded_spawned_in_conflict": len(spawned),
        "collisions_without_system": nom_coll, "collisions_with_system": act_coll,
        "contacts_with_system": act_contact,
        "timely_detection": round(timely / len(conf), 3) if conf else None,
        "false_alarm_rate": round(sum(1 for c in nonc if c["first_alert_t"] is not None) / len(nonc), 3)
        if nonc else None,
        "median_lead_s": round(statistics.median(leads), 2) if leads else None,
        "alert_latency_ms_p50": round(lat[len(lat) // 2]) if lat else None,
        "alert_latency_ms_p95": round(lat[int(0.95 * (len(lat) - 1))]) if lat else None,
        "forklift_time_lost_s_per_episode": round(sum(lost) / max(1, len(lost)), 2),
        "worker_stops": stops,
        "samples_delivered": sent, "samples_dropped": sum(p.dropped for p in pubs),
        "samples_superseded": sum(p.skipped for p in pubs),
        "combos": combos,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", default=["all"])
    ap.add_argument("--out", default="results/online_sim.json")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--cse", default="mobius", choices=["mobius", "acme"])
    ap.add_argument("--rounds", type=int, help="override rounds per case (quick checks)")
    ap.add_argument("--policy", help="YAML with a `risk:` section to override (e.g. config/policy_trained.yaml)")
    a = ap.parse_args()
    cse = ({"base_url": "http://127.0.0.1:7579", "cse_rn": "Mobius", "origin": "SEdgeGuard", "rvi": "2a"}
           if a.cse == "mobius" else
           {"base_url": "http://127.0.0.1:8080", "cse_rn": "cse-in", "origin": "CEdgeGuard", "rvi": "3"})
    if a.policy:
        POLICY.update(yaml.safe_load(open(a.policy)).get("risk", {}))
    names = list(CASES) if a.cases == ["all"] else a.cases
    sink = AlertSink(9091)
    results = []
    if os.path.exists(a.out) and a.cases != ["all"]:
        results = [r for r in json.load(open(a.out))["results"] if r["case"] not in names]
    for i, n in enumerate(names):
        case = dict(BASE_CASE, **CASES[n])
        if a.rounds:
            case["rounds"] = a.rounds
        r = run_case(n, case, cse, sink, a.seed + i, scen_seed=a.seed)
        results.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != "combos"}), flush=True)
        json.dump({"results": results, "lead_required_s": LEAD_REQ, "r_contact_m": R_CONTACT,
                   "r_collide_m": R_COLLIDE}, open(a.out, "w"), indent=1)
    subprocess.run(["bash", "scripts/mec.sh", "stop"], cwd=ROOT, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
