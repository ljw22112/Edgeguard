"""Reacting virtual devices on a real CSE: workers and forklifts that obey the alerts.

    python devices/live_devices.py --scene crossing          # one scene
    python devices/live_devices.py --scene all --loop        # demo loop (dashboard / video)

devices/device_sim.py replays fixed trajectories (good for measuring lead time).  Here every worker
and forklift is a simulated body that reacts to what the MEC app sends through oneM2M - the same
models as the closed-loop evaluation (sim/online_sim.Mover):
  worker tag    : WAIT until GO, STEP ASIDE to the lane edge (edgeguard/worker_cue.py behaviour)
  forklift      : one speed plan per worker, tightest applies; heartbeat fail-safe
Every device writes its own samples into its own AE (<CSE>/<device>/location | motion) at 10 Hz and
listens on the device_sim port for `alert` / `control` notifications.  Real boards can take over
the actuation of any device (firmware HIL mode, docs/hardware-demo.md) while this script keeps
supplying the positions.

Scenes (site metres; aisles along x at y = 0):
  crossing   worker crosses the aisle in front of a forklift           -> WAIT, then GO behind it
  head_on    worker walks down the aisle toward a forklift             -> STEP ASIDE, forklift passes
  two_trucks worker crosses between two forklifts from both sides      -> one WAIT per forklift, GO after both
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard import config                               # noqa: E402
from edgeguard.onem2m import parse_notification, now_ms    # noqa: E402
from sim.online_sim import Mover, Path                     # noqa: E402

DT = 0.1


def line(p0, p1, v, t0, n):
    """(start time, positions every DT): move from p0 to p1 at v m/s from t0 on, then stay."""
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    out = []
    for k in range(n):
        s = min(L, k * DT * v)
        out.append((x0 + (x1 - x0) * s / L, y0 + (y1 - y0) * s / L))
    return t0, out


def scene(name, n=int(22 / DT)):
    """-> {device: (kind, points)}; forklifts drive along +x / -x, heading from the path."""
    if name == "crossing":
        return {"worker_01": ("worker", line((0.0, -7.0), (0.0, 9.0), 1.2, 1.0, n)),
                "forklift_01": ("forklift", line((-16.0, 0.0), (26.0, 0.0), 2.2, 0.0, n))}
    if name == "head_on":
        return {"worker_01": ("worker", line((14.0, 0.4), (-8.0, 0.4), 1.0, 0.5, n)),
                "forklift_01": ("forklift", line((-12.0, 0.0), (26.0, 0.0), 2.0, 0.0, n))}
    if name == "two_trucks":
        return {"worker_01": ("worker", line((1.0, -7.0), (1.0, 9.0), 1.2, 1.5, n)),
                "forklift_01": ("forklift", line((-16.0, 0.0), (26.0, 0.0), 2.0, 0.0, n)),
                "forklift_02": ("forklift", line((20.0, 2.5), (-22.0, 2.5), 2.0, 0.0, n))}
    raise SystemExit(f"unknown scene {name}")


SCENES = ["crossing", "head_on", "two_trucks"]


class Live:
    def __init__(self, cfg):
        self.cfg = cfg
        self.paths = config.paths(cfg)
        self.lock = threading.Lock()
        self.movers, self.t0 = {}, time.time()
        self.clients = {}
        self.pool = ThreadPoolExecutor(8)
        self.log = []

    def client(self, dev):
        if dev not in self.clients:
            self.clients[dev] = config.device_client(self.cfg, dev)
        return self.clients[dev]

    def load(self, name):
        with self.lock:
            self.movers, self.start = {}, {}
            for dev, (kind, (t_start, pts)) in scene(name).items():
                self.start[dev] = t_start
                if kind == "worker":
                    self.movers[dev] = Mover(dev, "worker", Path(pts))
                else:
                    meta = []
                    for i in range(len(pts)):
                        (xa, ya), (xb, yb) = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
                        meta.append((math.atan2(yb - ya, xb - xa) if (xa, ya) != (xb, yb) else 0.0, 1, 0.0))
                    # heading of a parked truck: its direction of travel
                    first = next((m for m in meta if m[0] != 0.0), meta[0])
                    meta = [m if (pts[i] != pts[min(len(pts) - 1, i + 1)]) else first for i, m in enumerate(meta)]
                    self.movers[dev] = Mover(dev, "forklift", Path(pts, meta))
            self.t0 = time.time()

    def now(self):
        return time.time() - self.t0

    def on_notification(self, a):
        t = self.now()
        with self.lock:
            if "rates" in a or a.get("hb"):                     # <MEC AE>/control heartbeat
                for m in self.movers.values():
                    if m.kind == "forklift":
                        m.pending.append((t, "hb", None, ""))
                return
            ev, w, f = a.get("event"), a.get("worker"), a.get("forklift")
            acts = a.get("actions") or {}
            if f in self.movers and ev not in ("wait", "release", "aside"):
                fa = acts.get(f) or {}
                self.movers[f].on_alert(t, ev, None if ev == "clear" else fa.get("speed_limit"), src=w)
            if w in self.movers:
                wa = acts.get(w) or {}
                self.movers[w].on_alert(t, ev, wa.get("aside"), vibrate=wa.get("vibrate"), src=f)
            self.log.append((round(t, 1), ev, w, f))
            self._twin_state(ev, w, f, acts)

    def _twin_state(self, ev, w, f, acts):
        """SDT data model: each device reports what it now shows / enforces in its own twin
        (worker tag: cue module, forklift module: speedLimit module)."""
        twins = self.paths.get("twin") or {}
        if w in twins and w in self.movers:
            cue = {"aside": "ASIDE", "release": "GO", "clear": "GO"}.get(ev, "WAIT")
            self.pool.submit(self._update, w, f"{twins[w]}/cue", "egs:wrkCe", {"cueSe": cue, "cueSo": f or ""})
        if f in twins and f in self.movers and ev not in ("wait", "release", "aside"):
            from edgeguard import sdt
            attrs = sdt.speed_limit_from_alert({"event": ev, "forklift": f, "worker": w, "actions": acts})
            self.pool.submit(self._update, f, f"{twins[f]}/speedLimit", "egs:spdLt", attrs)

    def _update(self, dev, path, tp, attrs):
        try:
            self.client(dev).update_fcnt(path, tp, attrs)
        except Exception as e:
            print(f"twin {dev}: {e}", file=sys.stderr)

    def step(self):
        t = self.now()
        with self.lock:
            samples = []
            for dev, m in self.movers.items():
                if t >= self.start[dev]:            # (a Path is arc-length based: waiting is done here)
                    m.step(t, DT)
                x, y = m.pos()
                if m.kind == "worker":
                    samples.append((dev, self.paths["workers"][dev], {"id": dev, "kind": "worker", "ts": now_ms(),
                                                                       "x": round(x, 3), "y": round(y, 3)}))
                else:
                    s = m.sample()
                    samples.append((dev, self.paths["forklifts"][dev], {
                        "id": dev, "kind": "forklift", "ts": now_ms(), "x": round(x, 3), "y": round(y, 3),
                        "speed": round(s["speed"], 3), "heading": round(s["heading"], 4), "yaw_rate": 0.0}))
        for dev, path, con in samples:
            self.pool.submit(self._send, dev, path, con)
        return t

    def _send(self, dev, path, con):
        try:
            self.client(dev).publish(path, con)
        except Exception as e:                                   # keep playing; the CSE may be restarting
            print(f"publish {dev}: {e}", file=sys.stderr)


def serve(live, port):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            self.send_response(200)
            self.send_header("X-M2M-RSC", "2000")
            self.end_headers()
            kind, a = parse_notification(body)
            if kind == "cin" and isinstance(a, dict):
                live.on_notification(a)

        def log_message(self, *args):
            pass
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--scene", default="crossing", help=" | ".join(SCENES + ["all"]))
    ap.add_argument("--seconds", type=float, default=20.0, help="length of each scene")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--start-delay", type=float, default=0.0)
    ap.add_argument("--marks", help="write scene start times (JSON lines) here, for the video captions")
    a = ap.parse_args()
    cfg = config.load(a.config)
    live = Live(cfg)
    serve(live, cfg["device_sim"]["listen_port"])
    time.sleep(a.start_delay)
    names = SCENES if a.scene == "all" else [a.scene]
    while True:
        for name in names:
            live.load(name)
            if a.marks:
                with open(a.marks, "a") as fh:
                    fh.write(json.dumps({"scene": name, "wall": time.time()}) + "\n")
            print(f"scene {name}", flush=True)
            while live.now() < a.seconds:
                t_next = live.t0 + (round(live.now() / DT) + 1) * DT
                live.step()
                time.sleep(max(0.0, t_next - time.time()))
            events = [e for e in live.log if e[1] in ("raise", "aside", "release", "clear")]
            print(f"  events: {events[:12]}", flush=True)
            live.log.clear()
            time.sleep(1.5)                      # let the tracks go stale between scenes
        if not a.loop:
            break


if __name__ == "__main__":
    main()
