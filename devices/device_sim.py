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
QUIET = False
EP = {"t0": None, "contact": None, "first_alert_lead": []}   # lead time of the first alert per episode


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
        if "rates" in a:              # adaptive-rate command: the playback always runs at 10 Hz
            return
        lat = now_ms() - a["src_ts"] if a.get("src_ts") else None
        if a["event"] in ("raise", "refresh") and EP["t0"] and EP["contact"] is not None and not EP.get("seen"):
            EP["seen"] = True
            EP["first_alert_lead"].append(round(EP["contact"] - (time.time() - EP["t0"]), 2))
        if lat is not None and a["event"] in ("raise", "refresh"):
            latencies.append(lat)
        w, f = a["worker"], a["forklift"]
        acts = a["actions"]
        lat_s = f"{lat} ms" if lat is not None else "?"
        if QUIET:
            return
        if a["event"] == "clear":
            print(f"  [{w}] stop vibrating   [{f}] resume normal speed   (e2e {lat_s})")
        else:
            who = f"[{w}] VIBRATE ({a['level']})" if acts.get(w, {}).get("vibrate") else f"[{w}] no tag ({a['level']})"
            print(f"  {who}   [{f}] beacon on, speed x{acts[f]['speed_scale']:.2f}"
                  f"   e2e {lat_s}  | {a['reason']}")

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--scenario", default="crossing_conflict",
                    choices=[g.__name__[4:] for g in scenarios.GENERATORS] + ["mix"])
    ap.add_argument("--site-spread", action="store_true",
                    help="place each episode at one of the site's aisle intersections (for heatmaps)")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--start-delay", type=float, default=0.0)
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed factor")
    ap.add_argument("--noise", type=float, default=0.15, help="UWB position noise (m)")
    ap.add_argument("--runs", type=int, default=1, help="episodes to play (seeds seed..seed+runs-1)")
    ap.add_argument("--json-out", help="write alert latencies and counts to this file")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--uwb-dropout", help="START,END seconds: worker tag silent (radio shadow)")
    ap.add_argument("--mec-mock", help="MEC mock URL: publish network-based worker fixes + cell load")
    ap.add_argument("--untagged", action="store_true",
                    help="worker has no tag: only the camera node sees them (5 Hz detections)")
    ap.add_argument("--congest", help="START,END seconds: set the site cell to 90%% PRB load")
    a = ap.parse_args()

    global QUIET
    QUIET = a.quiet
    cfg = config.load(a.config)
    cse = config.client(cfg)
    paths = config.paths(cfg)
    sec = cfg.get("security") or {}
    clients = {}                                  # per-device originators when ACPs are on

    def dev_client(dev):
        if not sec.get("enabled"):
            return cse
        if dev not in clients:
            from edgeguard.onem2m import OneM2MClient
            cc = cfg["cse"]
            clients[dev] = OneM2MClient(cc["base_url"], cc["cse_rn"], sec["originators"][dev],
                                        str(cc.get("rvi", "3")))
        return clients[dev]
    w_id, f_id = next(iter(paths["workers"])), next(iter(paths["forklifts"]))

    srv = ThreadingHTTPServer(("0.0.0.0", cfg["device_sim"]["listen_port"]), AlertHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"alert listener on :{cfg['device_sim']['listen_port']}")
    time.sleep(a.start_delay)

    failures = 0
    drop = tuple(map(float, a.uwb_dropout.split(","))) if a.uwb_dropout else None
    cong = tuple(map(float, a.congest.split(","))) if a.congest else None
    mock = None
    if a.mec_mock:
        import requests as _rq
        from edgeguard.mec_services import SiteFrame
        ms = cfg.get("mec_services") or {}
        frame = SiteFrame(ms["origin"]["lat"], ms["origin"]["lon"])
        ue = (ms.get("users") or {}).get(w_id, "acr:10.100.0.1")
        mock = _rq.Session()

        def set_cell(load):
            mock.post(f"{a.mec_mock}/_mock/cells/{ms.get('cell_id', 'cell01')}",
                      json={"dl_gbr_prb_usage_cell": load / 2, "dl_nongbr_prb_usage_cell": load / 2,
                            "ul_gbr_prb_usage_cell": 10, "ul_nongbr_prb_usage_cell": 10}, timeout=1)
        set_cell(30)
    for run in range(a.runs):
        rng = random.Random(a.seed + run)
        if a.scenario == "mix":
            gen = rng.choice(scenarios.GENERATORS)
        else:
            gen = next(g for g in scenarios.GENERATORS if g.__name__[4:] == a.scenario)
        name, times, wk, fk = gen(rng)
        if a.site_spread:                          # busy crossings get more traffic
            ox, oy = rng.choices([(6, 6), (22, 6), (22, 20), (38, 13)], weights=[4, 3, 2, 1])[0]
            wk = [(x + ox, y + oy) for x, y in wk]
            fk = [(x + ox, y + oy, th, sp, yw) for x, y, th, sp, yw in fk]
        gt = scenarios.ground_truth(times, wk, fk)
        print(f"scenario {name} (seed {a.seed + run}): ground-truth conflict={gt['conflict']} "
              f"contact={gt['t_contact']} min distance={gt['d_min']:.2f} m")
        t0 = time.time()
        EP.update(t0=t0, contact=gt["t_contact"], seen=False)
        for t, (wx, wy), (fx, fy, th, sp, yaw) in zip(times, wk, fk):
            if gt["conflict"] and t > gt["t_contact"] + 1.0:
                break
            while time.time() - t0 < t / a.speed:
                time.sleep(0.002)
            ts = now_ms()
            if mock is not None and int(round(t * 10)) % 2 == 0:       # network fix at 5 Hz, ~1 m error
                lat, lon = frame.to_latlon(wx + rng.gauss(0, 0.8), wy + rng.gauss(0, 0.8))
                try:
                    mock.post(f"{a.mec_mock}/_mock/users/{ue}", json={"lat": lat, "lon": lon, "accuracy": 1.0},
                              timeout=1)
                    if cong:
                        set_cell(90 if cong[0] <= t < cong[1] else 30)
                except Exception:
                    pass
            silent = (drop is not None and drop[0] <= t < drop[1]) or a.untagged
            if a.untagged and int(round(t * 10)) % 2 == 0:
                cam_id, cam_path = next(iter(paths["cameras"].items()))
                try:
                    dev_client(cam_id).create_cin(cam_path, {"id": cam_id, "kind": "camera", "ts": ts, "persons": [
                        {"x": round(wx + rng.gauss(0, 0.3), 2), "y": round(wy + rng.gauss(0, 0.3), 2),
                         "conf": 0.8}]})
                except Exception:
                    failures += 1
            if drop and silent and not a.quiet and abs(t - drop[0]) < 0.05:
                print(f"  -- t={t:.1f}s worker UWB tag shadowed until {drop[1]:.1f}s --")
            try:
                if not silent:
                    dev_client(w_id).create_cin(paths["workers"][w_id], {
                        "id": w_id, "kind": "worker", "ts": ts,
                        "x": round(wx + rng.gauss(0, a.noise), 3), "y": round(wy + rng.gauss(0, a.noise), 3)})
                dev_client(f_id).create_cin(paths["forklifts"][f_id], {
                    "id": f_id, "kind": "forklift", "ts": ts,
                    "x": round(fx + rng.gauss(0, a.noise), 3), "y": round(fy + rng.gauss(0, a.noise), 3),
                    "speed": round(sp, 3), "heading": round(th, 4), "yaw_rate": round(yaw, 4)})
            except Exception as e:                      # CSE unreachable: keep the clock running
                failures += 1
                if failures in (1, 10, 100):
                    print(f"  sample write failed ({failures}x): {type(e).__name__}")
            if gt["conflict"] and abs(t - gt["t_contact"]) < 0.05 and not a.quiet:
                print(f"  -- t={t:.1f}s would-be contact point --")
        time.sleep(2.5 if run < a.runs - 1 else 1.0)    # let tracks go stale between episodes
    if latencies:
        print(f"alerts received: {len(latencies)}, end-to-end latency "
              f"median {statistics.median(latencies):.0f} ms, max {max(latencies)} ms")
    else:
        print("no alerts received")
    if EP["first_alert_lead"]:
        print("first alert lead time before contact (s):", EP["first_alert_lead"])
    if a.json_out:
        with open(a.json_out, "w") as fh:
            json.dump({"latencies_ms": latencies, "alerts": len(latencies),
                       "write_failures": failures, "runs": a.runs, "scenario": a.scenario,
                       "first_alert_lead_s": EP["first_alert_lead"]}, fh)
    srv.shutdown()


if __name__ == "__main__":
    main()
