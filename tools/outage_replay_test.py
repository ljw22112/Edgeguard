"""End-to-end store-and-forward test: cut the WAN to the cloud CSE mid-run, restore it,
and check that every alert the MEC app raised reaches the cloud copy.

    python tools/outage_replay_test.py --outage-at 12 --outage-s 25 --out results/outage_replay.json

Topology: edge Mobius (:7579) + MEC app + cloud copy over tools/wan_proxy.py (:17579 -> :7579,
AE EdgeGuard_site01). Killing the proxy is the outage. Needs Mobius running on :7579.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from topology_bench import PY, cfg_for, start, wait_http, write_cfg      # noqa: E402

H = {"X-M2M-Origin": "SEdgeGuardCloud", "X-M2M-RVI": "2a", "Accept": "application/json"}
CLOUD_AE = "http://127.0.0.1:7579/Mobius/EdgeGuard_site01"


def cloud_cins(cnt):
    r = requests.get(f"{CLOUD_AE}/{cnt}?rcn=4", headers={**H, "X-M2M-RI": "chk"}, timeout=5)
    if not r.ok:
        return []
    body = r.json()
    holder = body.get("m2m:cnt") or body.get("m2m:rsp") or {}      # Mobius answers rcn=4 as m2m:rsp
    cins = holder.get("m2m:cin", [])
    return sorted(cins, key=lambda c: c.get("ct", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=8, help="crossing-conflict encounters")
    ap.add_argument("--outage-at", type=float, default=12.0, help="s after start")
    ap.add_argument("--outage-s", type=float, default=25.0)
    ap.add_argument("--out", default="results/outage_replay.json")
    a = ap.parse_args()

    requests.delete(CLOUD_AE, headers={**H, "X-M2M-RI": "del"}, timeout=5)     # clean cloud copy
    c, _ = cfg_for("edge_in_sync")
    c["cloud_sync"]["risk_hz"] = 1
    cfg = write_cfg(c)
    proxy_cmd = [PY, "tools/wan_proxy.py", "--listen", "17579", "--target", "127.0.0.1:7579",
                 "--delay-ms", "25", "--jitter-ms", "5"]
    procs, timeline = [], []
    proxy = start(proxy_cmd)
    wait_http("http://127.0.0.1:17579/")
    mec = start([PY, "-m", "uvicorn", "mec_app.app:app", "--port", "9090", "--log-level", "warning"],
                env=dict(os.environ, EDGEGUARD_CONFIG=cfg), log="/tmp/eg_mec_outage.log")
    procs.append(mec)
    wait_http("http://127.0.0.1:9090/health")
    out = tempfile.mktemp(suffix=".json")
    t0 = time.time()
    sim = start([PY, "devices/device_sim.py", "--config", cfg, "--scenario", "crossing_conflict",
                 "--runs", str(a.runs), "--start-delay", "4", "--quiet", "--json-out", out],
                log="/tmp/eg_dev_outage.log")
    time.sleep(1.5)
    subprocess.run([PY, "tools/setup_resources.py", "--config", cfg, "--reset"], cwd=ROOT,
                   capture_output=True, check=True)

    health = lambda: requests.get("http://127.0.0.1:9090/health", timeout=2).json()   # noqa: E731
    samples = []

    def watch():
        while sim.poll() is None:
            try:
                h = health()
                samples.append({"t": round(time.time() - t0, 1), **{k: h["cloud"].get(k) for k in
                                ("sent", "backlog", "failed_attempts", "online")},
                                "alerts_sent": h["alerts_sent"]})
            except Exception:
                pass
            time.sleep(1.0)
    threading.Thread(target=watch, daemon=True).start()

    nonlocal_proxy = {"p": proxy}

    def outage():
        time.sleep(max(0.0, a.outage_at - (time.time() - t0)))
        nonlocal_proxy["p"].terminate()
        nonlocal_proxy["p"].wait(timeout=5)
        timeline.append({"event": "wan_down", "t": round(time.time() - t0, 1)})
        time.sleep(a.outage_s)
        nonlocal_proxy["p"] = start(proxy_cmd)
        timeline.append({"event": "wan_up", "t": round(time.time() - t0, 1)})
    th = threading.Thread(target=outage, daemon=True)
    th.start()
    try:
        sim.wait(timeout=900)
        th.join()
        h = health()
        deadline = time.time() + 90                       # let the backlog drain after the outage
        while time.time() < deadline and (h["cloud"]["backlog"] or h["cloud"]["online"] is False):
            time.sleep(1.0)
            h = health()
        time.sleep(1.0)
        h = health()
        alerts_cloud = cloud_cins("alert")
        risk_cloud = cloud_cins("risk")
        con = [c.get("con", {}) for c in alerts_cloud]
        keys = [(x.get("mec_tx_ts"), x.get("worker"), x.get("forklift"), x.get("event"))
                for x in con if isinstance(x, dict)]
        dev = json.load(open(out)) if os.path.exists(out) else {}
        res = {
            "runs": a.runs, "outage": timeline, "outage_s": a.outage_s,
            "alerts_raised_by_mec": h["alerts_sent"],
            "alerts_received_by_devices_during_run": dev.get("alerts"),
            "alerts_in_cloud": len(alerts_cloud), "risk_summaries_in_cloud": len(risk_cloud),
            "unique_alerts_in_cloud": len(set(keys)), "duplicates_in_cloud": len(keys) - len(set(keys)),
            "cloud_sync": h["cloud"], "health_trace": samples,
        }
        res["all_alerts_replayed"] = res["unique_alerts_in_cloud"] == res["alerts_raised_by_mec"]
        print(json.dumps({k: v for k, v in res.items() if k != "health_trace"}, indent=1))
        os.makedirs(os.path.dirname(os.path.join(ROOT, a.out)), exist_ok=True)
        json.dump(res, open(os.path.join(ROOT, a.out), "w"), indent=1)
    finally:
        for p in procs + [nonlocal_proxy["p"], sim]:
            p.terminate()
        os.unlink(cfg)


if __name__ == "__main__":
    main()
