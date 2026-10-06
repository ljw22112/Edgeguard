"""End-to-end run of the MEC Sandbox path with our warehouse scenario.

    python tools/sandbox_e2e.py --source cse --gis-period 1.0 --duration 120

  mec_mock (plays scenarios/edgeguard-warehouse.yaml like the Sandbox GIS engine)
    -> Location API (MEC 013) / RNIS (MEC 012)
    -> tools/mec_ipe.py (MEC-IPE stand-in) -> Mobius: MEC-IPE/location/<ue>, MEC-IPE/rnis/<cell>
    -> MEC app (subscribed to those containers) -> alerts -> device notification sink
  (--source direct: the MEC app polls the MEC APIs itself, no IPE)

Scored against the scenario's exact trajectories: every worker-forklift contact
(centre distance < 1.5 m) should be alerted >= 1 s before it.  The Sandbox UEs follow fixed
tracks and do not react, so this measures detection, not avoidance.
Needs Mobius on :7579 (scripts/setup_mobius.sh).
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.onem2m import parse_notification                 # noqa: E402
from mec_mock.scenario_player import ScenarioPlayer             # noqa: E402

PY = sys.executable
SCENARIO = os.path.join(ROOT, "scenarios", "edgeguard-warehouse.yaml")
R_CONTACT, LEAD_REQ, WINDOW, WARMUP = 1.5, 1.0, 8.0, 6.0


def start(cmd, env=None, log=None):
    return subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=open(log or os.devnull, "w"), stderr=subprocess.STDOUT)


def wait_http(url, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            requests.get(url, timeout=1)
            return True
        except requests.RequestException:
            time.sleep(0.2)
    raise RuntimeError(f"{url} did not come up")


class Sink:
    def __init__(self, port):
        self.alerts = []
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
                if kind == "cin" and isinstance(a, dict) and "event" in a:
                    sink.alerts.append((time.time(), a))

            def log_message(self, *x):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


def make_cfg(source, ipe_root):
    c = yaml.safe_load(open(os.path.join(ROOT, "config", "site.yaml")))
    c["cse"] = {"base_url": "http://127.0.0.1:7579", "cse_rn": "Mobius", "origin": "SEdgeGuard", "rvi": "2a"}
    ms = c["mec_services"]
    ms.update(enabled=True, location_source=source, base_url="http://127.0.0.1:8085")
    ms.setdefault("ipe", {})["root"] = ipe_root
    ids = {v["kind"]: [] for v in ms["ue_map"].values()}
    for v in ms["ue_map"].values():
        ids[v["kind"]].append(v["id"])
    c["devices"] = {"workers": ids.get("worker", []), "forklifts": ids.get("forklift", []), "cameras": []}
    c["mec"]["notify_url"] = "http://127.0.0.1:9090/notify"
    c["device_sim"]["notify_url"] = "http://127.0.0.1:9091/alert"
    c["cloud_sync"]["enabled"] = False
    c["security"]["enabled"] = False
    c["rate_control"]["enabled"] = False          # Sandbox UEs are not ours to command
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="eg_sbx_")
    with os.fdopen(fd, "w") as fh:
        yaml.safe_dump(c, fh)
    return path, c


def ground_truth(t0, duration, ue_map):
    p = ScenarioPlayer.load(SCENARIO, period=0, t0=0)
    W = [a for a, v in ue_map.items() if v["kind"] == "worker"]
    F = [a for a, v in ue_map.items() if v["kind"] == "forklift"]
    contacts, dist = [], {}
    prev = {}
    for k in range(int(duration * 10) + int(WINDOW * 10)):
        t = k * 0.1
        u = p.users(t)
        xy = {a: p.frame.xy(u[a]["lon"], u[a]["lat"]) for a in W + F}
        for w in W:
            for f in F:
                key = (ue_map[w]["id"], ue_map[f]["id"])
                d = math.dist(xy[w], xy[f])
                dist.setdefault(key, []).append(d)
                inside = d < R_CONTACT
                if inside and not prev.get(key) and WARMUP <= t <= duration - 1:
                    contacts.append((key, round(t, 1)))
                prev[key] = inside
    return contacts, dist


def score(alerts, t0, duration, ue_map):
    contacts, dist = ground_truth(t0, duration, ue_map)
    ev = {}
    for rx, a in alerts:
        if a.get("event") in ("raise", "refresh"):
            ev.setdefault((a["worker"], a["forklift"]), []).append(rx - t0)
    rows, timely, detected, leads = [], 0, 0, []
    for key, tc in contacts:
        win = [t for t in ev.get(key, []) if tc - WINDOW <= t <= tc]
        first = min(win) if win else None
        ok = first is not None and tc - first >= LEAD_REQ
        timely += ok
        detected += first is not None
        if first is not None:
            leads.append(tc - first)
        rows.append({"pair": key, "t_contact": tc, "first_alert": None if first is None else round(first, 2),
                     "timely": ok})
    # false alarm: a raise with no contact (d < 1.5 m) and no near miss (d < 3 m) in the next 8 s
    fa, raises = 0, 0
    for rx, a in alerts:
        if a.get("event") != "raise":
            continue
        t = rx - t0
        if t < WARMUP:
            continue
        raises += 1
        d = dist.get((a["worker"], a["forklift"]), [])
        seg = d[int(t * 10): int((t + WINDOW) * 10)]
        if seg and min(seg) > 3.0:
            fa += 1
    lat = sorted((rx * 1000 - a["src_ts"]) for rx, a in alerts if a.get("src_ts") and a.get("event") != "clear")
    by_pair = {}
    for r in rows:
        k = f"{r['pair'][0]}-{r['pair'][1]}"
        b = by_pair.setdefault(k, {"contacts": 0, "timely": 0})
        b["contacts"] += 1
        b["timely"] += r["timely"]
    return {"contacts": len(contacts), "timely": timely, "detected": detected,
            "timely_rate": round(timely / len(contacts), 3) if contacts else None,
            "median_lead_s": round(sorted(leads)[len(leads) // 2], 2) if leads else None,
            "raises": raises, "false_alarm_raises": fa,
            "fix_to_alert_ms_p50": round(lat[len(lat) // 2]) if lat else None,
            "fix_to_alert_ms_p95": round(lat[int(0.95 * (len(lat) - 1))]) if lat else None,
            "by_pair": by_pair, "contacts_detail": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["cse", "direct"], default="cse")
    ap.add_argument("--gis-period", type=float, default=1.0, help="Sandbox position refresh (s)")
    ap.add_argument("--duration", type=float, default=120)
    ap.add_argument("--accuracy", type=float, default=1.0, help="accuracy (m) the Location API reports")
    ap.add_argument("--noise", type=float, default=0.0, help="position error (m, std) added to each fix")
    ap.add_argument("--out")
    a = ap.parse_args()
    label = f"{a.source}_{a.gis_period:g}s"
    out = a.out or os.path.join(ROOT, "results", f"sandbox_e2e_{label}.json")
    cfg_path, cfg = make_cfg(a.source, "MEC-IPE")
    ue_map = cfg["mec_services"]["ue_map"]
    procs = []
    sink = Sink(9091)
    try:
        h = {"X-M2M-Origin": "SMecIpe", "X-M2M-RI": "del", "X-M2M-RVI": "2a"}
        requests.delete("http://127.0.0.1:7579/Mobius/MEC-IPE", headers=h, timeout=5)    # fresh IPE tree
        procs.append(start([PY, "-m", "uvicorn", "mec_mock.server:app", "--port", "8085", "--log-level", "warning"],
                           env=dict(os.environ, MEC_MOCK_SCENARIO=SCENARIO, MEC_MOCK_GIS_PERIOD=str(a.gis_period),
                                    MEC_MOCK_ACCURACY=str(a.accuracy), MEC_MOCK_NOISE=str(a.noise)),
                           log="/tmp/eg_sbx_mock.log"))
        wait_http("http://127.0.0.1:8085/_mock/stats")
        subprocess.run([PY, "tools/setup_resources.py", "--config", cfg_path, "--reset"], cwd=ROOT,
                       capture_output=True, check=True)
        if a.source == "cse":
            procs.append(start([PY, "tools/mec_ipe.py", "--config", cfg_path, "--duration", str(a.duration + 15)],
                               log="/tmp/eg_sbx_ipe.log"))
            time.sleep(2.0)                       # IPE creates its containers
        procs.append(start([PY, "-m", "uvicorn", "mec_app.app:app", "--port", "9090", "--log-level", "warning"],
                           env=dict(os.environ, EDGEGUARD_CONFIG=cfg_path), log="/tmp/eg_sbx_mec.log"))
        wait_http("http://127.0.0.1:9090/health")
        t0 = requests.get("http://127.0.0.1:8085/_mock/scenario", timeout=2).json()["t0"]
        t_end = t0 + a.duration
        while time.time() < t_end:
            time.sleep(1.0)
        health = requests.get("http://127.0.0.1:9090/health", timeout=2).json()
        mock = requests.get("http://127.0.0.1:8085/_mock/stats", timeout=2).json()
        res = {"source": a.source, "gis_period_s": a.gis_period, "duration_s": a.duration, "accuracy_m": a.accuracy, "noise_m": a.noise,
               **score(sink.alerts, t0, a.duration, ue_map),
               "mec_app": {k: health.get(k) for k in ("samples", "alerts_sent", "mec", "network", "ingest_ms_median")},
               "mock": mock}
        print(json.dumps({k: v for k, v in res.items() if k != "contacts_detail"}, indent=1))
        json.dump(res, open(out, "w"), indent=1)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        os.unlink(cfg_path)


if __name__ == "__main__":
    main()
