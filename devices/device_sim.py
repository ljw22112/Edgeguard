"""Virtual worker tag + forklift module (stand-in until the ESP32 boards arrive).

Plays a warehouse scenario in real time, writes samples to the CSE exactly as
the firmware will, and listens for `alert` notifications the way the worker
tag (vibrate) and forklift module (beacon / slow down) do.

    python devices/device_sim.py --scenario crossing_conflict --start-delay 3
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard import config                               # noqa: E402
from edgeguard.onem2m import parse_notification, now_ms    # noqa: E402
from sim import scenarios                                  # noqa: E402

latencies = []


class AlertHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        self.send_response(200)
        self.send_header("X-M2M-RSC", "2000")
        self.end_headers()
        kind, a = parse_notification(body)
        if kind != "cin" or not isinstance(a, dict):
            return
        lat = now_ms() - a["src_ts"] if a.get("src_ts") else None
        if lat is not None and a["event"] in ("raise", "refresh"):
            latencies.append(lat)
        w, f = a["worker"], a["forklift"]
        acts = a["actions"]
        lat_s = f"{lat} ms" if lat is not None else "?"
        if a["event"] == "clear":
            print(f"  [{w}] stop vibrating   [{f}] resume normal speed   (e2e {lat_s})")
        else:
            print(f"  [{w}] VIBRATE ({a['level']})   [{f}] beacon on, speed x{acts[f]['speed_scale']:.2f}"
                  f"   e2e {lat_s}  | {a['reason']}")

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--scenario", default="crossing_conflict",
                    choices=[g.__name__[4:] for g in scenarios.GENERATORS])
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--start-delay", type=float, default=0.0)
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed factor")
    ap.add_argument("--noise", type=float, default=0.15, help="UWB position noise (m)")
    a = ap.parse_args()

    cfg = config.load(a.config)
    cse = config.client(cfg)
    paths = config.paths(cfg)
    w_id, f_id = next(iter(paths["workers"])), next(iter(paths["forklifts"]))

    srv = ThreadingHTTPServer(("0.0.0.0", cfg["device_sim"]["listen_port"]), AlertHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"alert listener on :{cfg['device_sim']['listen_port']}")
    time.sleep(a.start_delay)

    rng = random.Random(a.seed)
    gen = next(g for g in scenarios.GENERATORS if g.__name__[4:] == a.scenario)
    name, times, wk, fk = gen(rng)
    gt = scenarios.ground_truth(times, wk, fk)
    print(f"scenario {name}: ground-truth conflict={gt['conflict']} "
          f"contact={gt['t_contact']} min distance={gt['d_min']:.2f} m")

    t0 = time.time()
    for t, (wx, wy), (fx, fy, th, sp, yaw) in zip(times, wk, fk):
        if gt["conflict"] and t > gt["t_contact"] + 1.0:
            break
        while time.time() - t0 < t / a.speed:
            time.sleep(0.002)
        ts = now_ms()
        cse.create_cin(paths["workers"][w_id], {
            "id": w_id, "kind": "worker", "ts": ts,
            "x": round(wx + rng.gauss(0, a.noise), 3), "y": round(wy + rng.gauss(0, a.noise), 3)})
        cse.create_cin(paths["forklifts"][f_id], {
            "id": f_id, "kind": "forklift", "ts": ts,
            "x": round(fx + rng.gauss(0, a.noise), 3), "y": round(fy + rng.gauss(0, a.noise), 3),
            "speed": round(sp, 3), "heading": round(th, 4), "yaw_rate": round(yaw, 4)})
        if gt["conflict"] and abs(t - gt["t_contact"]) < 0.05:
            print(f"  -- t={t:.1f}s would-be contact point --")
    time.sleep(1.0)
    if latencies:
        print(f"alerts received: {len(latencies)}, end-to-end latency "
              f"median {statistics.median(latencies):.0f} ms, max {max(latencies)} ms")
    else:
        print("no alerts received")
    srv.shutdown()


if __name__ == "__main__":
    main()
