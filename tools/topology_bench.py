"""Compare deployment topologies for EdgeGuard under an emulated WAN.

Topologies
  cloud      devices -> WAN -> Mobius IN-CSE (cloud) + MEC app in the cloud -> WAN -> devices
  edge_in    Mobius IN-CSE on the MEC host; no cloud copy
  edge_mn    ACME MN-CSE on the MEC host, registered to cloud Mobius IN-CSE over Mcc (WAN);
             alerts stay local, risk/alerts are copied to the cloud through MN-CSE retargeting

Prerequisites (already running): Mobius at :7579, ACME MN-CSE at :8081 whose registrar
address points at the WAN proxy port 17579.

    python tools/topology_bench.py --delay-ms 25 --runs 6 --out results/topology.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
BASE = yaml.safe_load(open(os.path.join(ROOT, "config", "edgeguard.yaml")))


def cfg_for(topo):
    c = copy.deepcopy(BASE)
    c["mec"]["notify_url"] = "http://127.0.0.1:9090/notify"
    c["device_sim"]["notify_url"] = "http://127.0.0.1:9091/alert"
    c["cloud_sync"] = {"enabled": False}
    if topo == "cloud":
        c["cse"] = {"base_url": "http://127.0.0.1:17579", "cse_rn": "Mobius", "origin": "SEdgeGuard", "rvi": "2a"}
        c["device_sim"]["notify_url"] = "http://127.0.0.1:19091/alert"      # cloud -> site over WAN
        mec_cse = {"base_url": "http://127.0.0.1:7579", "cse_rn": "Mobius", "origin": "SEdgeGuard", "rvi": "2a"}
        return c, mec_cse
    if topo == "edge_in":
        c["cse"] = {"base_url": "http://127.0.0.1:7579", "cse_rn": "Mobius", "origin": "SEdgeGuard", "rvi": "2a"}
        return c, None
    if topo == "edge_in_sync":
        # Mobius on the MEC host + application-level copy to a second (cloud) Mobius over the WAN.
        # Two IN-CSEs cannot register to each other, so this bridge is outside oneM2M Mcc.
        c["cse"] = {"base_url": "http://127.0.0.1:7579", "cse_rn": "Mobius", "origin": "SEdgeGuard", "rvi": "2a"}
        # own originator: on this one-PC bench the "cloud" is the same Mobius behind the WAN proxy,
        # and Mobius allows one AE per originator (SEdgeGuard already owns the site AE)
        c["cloud_sync"] = {"enabled": True, "base_url": "http://127.0.0.1:17579", "cse_rn": "Mobius",
                           "origin": "SEdgeGuardCloud", "rvi": "2a", "ae": "EdgeGuard_site01", "risk_hz": 1}
        return c, None
    if topo == "edge_mn":
        c["cse"] = {"base_url": "http://127.0.0.1:8081", "cse_rn": "cse-mn", "origin": "CEdgeGuard", "rvi": "3"}
        c["cloud_sync"] = {"enabled": True, "base_url": "http://127.0.0.1:8081", "cse_rn": "~/Mobius2/Mobius",
                           "origin": "CEdgeGuard", "rvi": "2a", "ae": "EdgeGuard_site01", "risk_hz": 1}
        return c, None
    raise ValueError(topo)


def write_cfg(c):
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="eg_")
    with os.fdopen(fd, "w") as fh:
        yaml.safe_dump(c, fh)
    return path


def start(cmd, env=None, log=None):
    return subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=open(log or os.devnull, "w"),
                            stderr=subprocess.STDOUT)


def wait_http(url, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            requests.get(url, timeout=1)
            return True
        except requests.RequestException:
            time.sleep(0.2)
    return False


def run_topology(topo, a, wan_up=True):
    dev_cfg, mec_cse = cfg_for(topo)
    mec_cfg = copy.deepcopy(dev_cfg)
    if mec_cse:
        mec_cfg["cse"] = mec_cse
    dpath, mpath = write_cfg(dev_cfg), write_cfg(mec_cfg)
    procs = []
    try:
        if wan_up:
            procs.append(start([PY, "tools/wan_proxy.py", "--listen", "17579", "--target", "127.0.0.1:7579",
                                "--delay-ms", str(a.delay_ms), "--jitter-ms", str(a.jitter_ms)]))
            procs.append(start([PY, "tools/wan_proxy.py", "--listen", "19091", "--target", "127.0.0.1:9091",
                                "--delay-ms", str(a.delay_ms), "--jitter-ms", str(a.jitter_ms)]))
        if wan_up:
            wait_http("http://127.0.0.1:17579/")
        if topo == "edge_mn":
            if wan_up:
                wait_registered()
            pin_registrar_poa()
            requests.delete("http://127.0.0.1:7579/Mobius/EdgeGuard_site01", timeout=3,
                            headers={"X-M2M-Origin": "CEdgeGuard", "X-M2M-RI": "del", "X-M2M-RVI": "2a"})
        env = dict(os.environ, EDGEGUARD_CONFIG=mpath)
        mec = start([PY, "-m", "uvicorn", "mec_app.app:app", "--port", "9090", "--log-level", "warning"],
                    env=env, log=f"/tmp/eg_mec_{topo}.log")
        procs.append(mec)
        wait_http("http://127.0.0.1:9090/health")
        out = tempfile.mktemp(suffix=".json")
        sim = start([PY, "devices/device_sim.py", "--config", dpath, "--scenario", "crossing_conflict",
                     "--runs", str(a.runs), "--start-delay", "4", "--quiet", "--json-out", out],
                    log=f"/tmp/eg_dev_{topo}.log")
        time.sleep(1.5)
        if wan_up or topo != "cloud":
            setup = subprocess.run([PY, "tools/setup_resources.py", "--config", mpath if topo == "cloud" else dpath,
                                    "--reset"], cwd=ROOT, capture_output=True, text=True)
            if setup.returncode:
                print(setup.stdout[-500:], setup.stderr[-800:])
        sim.wait(timeout=600)
        health = requests.get("http://127.0.0.1:9090/health", timeout=2).json()
        res = json.load(open(out)) if os.path.exists(out) else {"latencies_ms": [], "alerts": 0}
        lat = res["latencies_ms"]
        return {
            "topology": topo, "wan_up": wan_up, "runs": a.runs,
            "alerts_received": len(lat),
            "alert_latency_ms_median": statistics.median(lat) if lat else None,
            "alert_latency_ms_p95": sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else None,
            "sensor_to_mec_ms_median": health.get("ingest_ms_median"),
            "alerts_sent_by_mec": health.get("alerts_sent"),
            "write_failures": res.get("write_failures"),
            "cloud_sync": health.get("cloud"),
        }
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        time.sleep(1.0)


def wait_registered(timeout=60):
    """After a WAN gap the MN-CSE re-registers with the IN-CSE; wait until retargeting works."""
    h = {"X-M2M-Origin": "CEdgeGuard", "X-M2M-RI": "reg", "X-M2M-RVI": "2a", "Accept": "application/json"}
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get("http://127.0.0.1:8081/~/Mobius2/Mobius", headers=h, timeout=2).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    print("warning: MN-CSE not registered to the IN-CSE")
    return False


def pin_registrar_poa():
    """Route MN-CSE -> IN-CSE traffic through the WAN proxy.

    After registration the MN-CSE retargets requests to the poa that Mobius
    advertises (its host IP), which would bypass the proxy on this single test
    machine.  In a real deployment that address is across the WAN anyway."""
    h = {"X-M2M-Origin": "CAdmin", "X-M2M-RI": "pin", "X-M2M-RVI": "3",
         "Content-Type": "application/json", "Accept": "application/json"}
    r = requests.put("http://127.0.0.1:8081/cse-mn/Mobius2", headers=h, timeout=3,
                     data=json.dumps({"m2m:csr": {"poa": ["http://127.0.0.1:17579"]}}))
    return r.ok


def cloud_has_data():
    h = {"X-M2M-Origin": "SEdgeGuard", "X-M2M-RI": "chk", "X-M2M-RVI": "2a", "Accept": "application/json"}
    out = {}
    for c in ("risk", "alert"):
        r = requests.get(f"http://127.0.0.1:7579/Mobius/EdgeGuard_site01/{c}?ty=4&fu=1", headers=h, timeout=3)
        out[c] = len(r.json().get("m2m:uril", [])) if r.ok else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay-ms", type=float, default=25)
    ap.add_argument("--jitter-ms", type=float, default=5)
    ap.add_argument("--runs", type=int, default=6)
    ap.add_argument("--out", default="results/topology.json")
    ap.add_argument("--only", nargs="*", help="run only these topologies")
    ap.add_argument("--wan-down", action="store_true", help="with --only: emulate a WAN outage")
    a = ap.parse_args()
    results = []
    if a.only:
        for topo in a.only:
            print(json.dumps(run_topology(topo, a, wan_up=not a.wan_down)))
        return
    for topo in ("cloud", "edge_in", "edge_in_sync", "edge_mn"):
        r = run_topology(topo, a)
        if topo == "edge_mn":
            r["cloud_copy_in_mobius"] = cloud_has_data()
        results.append(r)
        print(json.dumps(r))
    # WAN outage: proxies not started
    for topo in ("cloud", "edge_in_sync", "edge_mn"):
        r = run_topology(topo, a, wan_up=False)
        results.append(r)
        print(json.dumps(r))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"delay_ms_one_way": a.delay_ms, "jitter_ms": a.jitter_ms, "results": results},
              open(a.out, "w"), indent=2)


if __name__ == "__main__":
    main()
