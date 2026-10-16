"""Soak and fault-injection test of the MEC app: does it keep protecting people for hours, through faults?

    scripts/acme.sh start in
    python tools/soak_test.py                    # about 4 minutes
    python tools/soak_test.py --minutes 1.5      # CI

The MEC app runs as its own process against an ACME IN-CSE.  Six worker tags and three forklift modules
publish 5 Hz through the CSE (each device under its own AE and originator); the forklifts drive up and
down three lanes and the workers keep crossing them, so alerts flow all the time.  A listener in the place
of the devices receives the alerts the MEC app writes, end to end through the CSE.

The MEC app and the devices reach the CSE through a local TCP proxy (tools/wan_proxy.py, no delay), so
the link can be cut without touching the CSE.  Faults, one after another:
  burst     2,000 notifications straight at /notify from 8 threads, a third of them malformed
            (not JSON, NaN, missing fields, wrong types, 200 kB strings)
  churn     a camera reports three people at new places every frame for 30 s: hundreds of untagged
            tracks that the app must forget again
  outage    the link to the CSE is cut for 10 s (proxy stopped): writes fail, nothing arrives
  reset     the CSE loses its state, as after a restore without its database: every AE, container and
            subscription is deleted; the devices notice (404) and register again
  wan       the cloud copy points at an unreachable address the whole time (store and forward)

Measured every 2 s: resident memory, threads, /health latency, tracks and internal tables, alerts
received by the devices and their end-to-end latency (device sample -> CSE -> MEC app -> CSE -> device).
Result: results/soak.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard import config                                    # noqa: E402
from edgeguard.onem2m import OneM2MClient, OneM2MError, parse_notification   # noqa: E402

MEC_PORT, DEV_PORT, PROXY_PORT = 9090, 9391, 18080
MEC = f"http://127.0.0.1:{MEC_PORT}"
WORKERS = [f"worker_s{i}" for i in range(1, 7)]
FORKLIFTS = [f"forklift_s{i}" for i in range(1, 4)]
CAMERA = "camera_s1"
LANES = (-6.0, 0.0, 6.0)


def override_file():
    d = os.path.join(ROOT, ".soak")
    os.makedirs(d, exist_ok=True)
    over = {"cse": {"base_url": f"http://127.0.0.1:{PROXY_PORT}", "cse_rn": "cse-in", "rvi": "3"},
            "onem2m": {"data_model": "cin", "zone_broadcast": {"zones": {}}},
            "devices": {"workers": WORKERS, "forklifts": FORKLIFTS, "cameras": [CAMERA]},
            "device_sim": {"notify_url": f"http://127.0.0.1:{DEV_PORT}/alert"},
            "mec": {"notify_url": f"http://127.0.0.1:{MEC_PORT}/notify", "track_gc_s": 10.0},
            "cloud_sync": {"enabled": True, "base_url": "http://127.0.0.1:9", "cse_rn": "cloud", "rvi": "3"},
            "mec_services": {"enabled": False}}
    path = os.path.join(d, "soak-overrides.yaml")
    yaml.safe_dump(over, open(path, "w"))
    return path


def kin(dev, t):
    """Forklift j drives up and down lane j; worker i keeps crossing all lanes at x = -10 + 4 i."""
    if dev.startswith("forklift"):
        j = FORKLIFTS.index(dev)
        w = 2 * math.pi / 16
        x, vx = 12 * math.sin(w * t + j), 12 * w * math.cos(w * t + j)
        return {"id": dev, "kind": "forklift", "x": round(x, 3), "y": LANES[j], "speed": round(abs(vx), 3),
                "heading": 0.0 if vx >= 0 else math.pi, "yaw_rate": 0.0}
    i = WORKERS.index(dev)
    w = 2 * math.pi / 22
    return {"id": dev, "kind": "worker", "x": -10 + 4 * i, "y": round(9 * math.sin(w * t + i), 3)}


class Devices:
    """The tags and forklift modules: publish through the CSE, receive alerts from it."""

    def __init__(self, cfg, hz):
        self.cfg, self.p, self.hz = cfg, config.paths(cfg), hz
        self.clients = {d: config.device_client(cfg, d) for d in WORKERS + FORKLIFTS + [CAMERA]}
        self.alerts, self.lat, self.lock = 0, [], threading.Lock()
        self.pub_ok, self.pub_fail, self.reregistered, self.reg_at = 0, 0, 0, {}
        self.stop = threading.Event()
        self.churn = threading.Event()
        dev = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                self.send_response(200)
                self.send_header("X-M2M-RSC", "2000")
                self.end_headers()
                kind, con = parse_notification(body)
                if kind == "cin" and isinstance(con, dict) and con.get("event"):
                    with dev.lock:
                        dev.alerts += 1
                        if con.get("src_ts"):
                            dev.lat.append((time.time(), time.time() * 1000 - con["src_ts"]))

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", DEV_PORT), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def register(self, only=None):
        """What a device does at boot (and again after the CSE lost its registration)."""
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from setup_resources import device_acp
        for d, c in self.clients.items():
            if only and d != only:
                continue
            group = "workers" if d in WORKERS else "forklifts" if d in FORKLIFTS else "cameras"
            path = self.p[group][d]
            try:
                c.with_retry(c.create_ae, d, f"Nedgeguard.{group[:-1]}")
            except OneM2MError as e:
                if e.rsc != "4117":                       # ACME: this originator already has its AE
                    raise
            c.with_retry(c.create_container, d, path.rsplit("/", 1)[1])
            device_acp(c, self.cfg, self.p, d, path)

    def subscribe_alerts(self):
        """The devices follow the MEC app's alert container (it exists once the MEC app has set it up)."""
        c = config.client(self.cfg)
        c.create_subscription(self.p["alert"], "sub_devices", [self.cfg["device_sim"]["notify_url"]])

    def run(self, t0):
        def loop(d):
            c, group = self.clients[d], "workers" if d in WORKERS else "forklifts"
            path = self.p[group][d]
            k = 0
            while not self.stop.is_set():
                t = time.time()
                try:
                    c.create_cin(path, {**kin(d, t - t0), "ts": int(t * 1000)})
                    self.pub_ok += 1
                except OneM2MError as e:
                    self.pub_fail += 1
                    if e.status == 404 and time.time() - self.reg_at.get(d, 0) > 2.0:   # the CSE forgot us
                        self.reg_at[d] = time.time()
                        try:
                            self.register(only=d)
                            self.reregistered += 1
                        except Exception:
                            pass
                except Exception:
                    self.pub_fail += 1
                k += 1
                time.sleep(max(0.0, t0 + k / self.hz - time.time() + (hash(d) % 97) / 1000))
        for d in WORKERS + FORKLIFTS:
            threading.Thread(target=loop, args=(d,), daemon=True).start()

        def camera():
            c, path, rng = self.clients[CAMERA], self.p["cameras"][CAMERA], random.Random(3)
            while not self.stop.is_set():
                if self.churn.is_set():
                    persons = [{"x": rng.uniform(-40, 40), "y": rng.uniform(15, 40)} for _ in range(3)]
                    try:
                        c.create_cin(path, {"id": CAMERA, "kind": "camera", "ts": int(time.time() * 1000), "persons": persons})
                    except Exception:
                        pass
                time.sleep(0.2)
        threading.Thread(target=camera, daemon=True).start()


def proc_stats(pid):
    try:
        rss = next(int(line.split()[1]) for line in open(f"/proc/{pid}/status") if line.startswith("VmRSS"))
        return rss / 1024, len(os.listdir(f"/proc/{pid}/task"))
    except (OSError, StopIteration):
        return None, None


def burst(n=2000, threads=8):
    """Valid and malformed notifications straight at /notify."""
    bad = [b"not json", b'{"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {"id": "worker_s1", "kind": "worker", "x": NaN, "y": 1}}}}}}',
           json.dumps({"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {"kind": "forklift", "x": "a", "y": []}}}}}}).encode(),
           json.dumps({"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {"id": "x" * 200000, "kind": "worker", "x": 1, "y": 1}}}}}}).encode(),
           json.dumps({"m2m:sgn": {"vrq": True}}).encode(), b"[]", b'{"m2m:sgn": null}']
    sent, errors = [0], [0]

    def w(k):
        s = requests.Session()
        rng = random.Random(k)
        for i in range(n // threads):
            if rng.random() < 0.33:
                body = rng.choice(bad)
            else:
                con = {"id": rng.choice(WORKERS), "kind": "worker", "x": rng.uniform(-10, 10), "y": rng.uniform(-9, 9),
                       "ts": int(time.time() * 1000)}
                body = json.dumps({"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": con}}, "net": 3}}}).encode()
            try:
                r = s.post(f"{MEC}/notify", data=body, headers={"Content-Type": "application/json"}, timeout=5)
                sent[0] += 1
                if r.status_code != 200:
                    errors[0] += 1
            except requests.RequestException:
                errors[0] += 1
    ts = [threading.Thread(target=w, args=(k,)) for k in range(threads)]
    t0 = time.time()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return {"sent": sent[0], "errors": errors[0], "secs": round(time.time() - t0, 2)}


class Proxy:
    def __init__(self):
        self.p = None

    def start(self):
        self.p = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "wan_proxy.py"), "--listen", str(PROXY_PORT),
                                   "--target", "127.0.0.1:8080", "--delay-ms", "0", "--jitter-ms", "0"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        for _ in range(50):
            try:
                import socket
                socket.create_connection(("127.0.0.1", PROXY_PORT), 0.2).close()
                return
            except OSError:
                time.sleep(0.1)

    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.kill()
            self.p.wait(5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=4.0)
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--app-dir", help="run the MEC app from this directory (e.g. an older version for a before/after)")
    ap.add_argument("--out", default="results/soak.json")
    a = ap.parse_args()
    total = a.minutes * 60
    over = override_file()
    env = dict(os.environ, EDGEGUARD_CONFIG=os.path.join(ROOT, "config", "site.yaml"),
               EDGEGUARD_OVERRIDES=",".join([os.path.join(ROOT, "config", "local-acme.yaml"), over]))
    os.environ.update({k: env[k] for k in ("EDGEGUARD_CONFIG", "EDGEGUARD_OVERRIDES")})
    cfg = config.load()

    admin = OneM2MClient("http://127.0.0.1:8080", cfg["cse"]["cse_rn"], "CAdmin")     # direct, not via the proxy
    proxy = Proxy()
    proxy.start()
    for rn in [cfg["ae"]] + WORKERS + FORKLIFTS + [CAMERA]:      # a clean CSE; the MEC app builds its own tree
        try:
            admin.delete(rn)
        except OneM2MError:
            pass
    log_path = os.path.join(ROOT, ".soak", "mec.log")
    app_env = dict(env, PYTHONPATH=os.pathsep.join(filter(None, [a.app_dir, ROOT, env.get("PYTHONPATH")])))
    mec = subprocess.Popen([sys.executable, "-m", "uvicorn", "mec_app.app:app", "--host", "127.0.0.1", "--port", str(MEC_PORT),
                            "--log-level", "warning"], cwd=a.app_dir or ROOT, env=app_env, stdout=open(log_path, "w"),
                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    for _ in range(150):
        try:
            if requests.get(f"{MEC}/health", timeout=1).ok:
                break
        except requests.RequestException:
            time.sleep(0.2)
    devs = Devices(cfg, a.hz)          # its alert listener must be up too: the CSE verifies both URLs
    # the resource tree after the MEC app is up: the CSE verifies its notification URL
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "setup_resources.py")], env=env,
                       capture_output=True, text=True, timeout=180, cwd=ROOT)
    if r.returncode != 0:
        mec.kill()
        raise SystemExit("::error title=soak::setup_resources failed: " + (r.stdout + r.stderr)[-400:].replace("\n", " | "))
    try:
        return run(a, total, cfg, mec, log_path, devs, proxy, admin)
    finally:
        if mec.poll() is None:
            mec.kill()
        proxy.stop()


def run(a, total, cfg, mec, log_path, devs, proxy, admin):
    devs.register()
    devs.subscribe_alerts()
    t0 = time.time()
    devs.run(t0)

    plan = {"burst": 0.15 * total, "churn": 0.25 * total, "outage": 0.55 * total, "reset": 0.72 * total}
    samples, events, health_ms = [], [], []
    done = set()
    recovery = {"outage": {}, "reset": {}}

    def health():
        t = time.time()
        try:
            h = requests.get(f"{MEC}/health", timeout=5).json()
            health_ms.append((round(t - t0, 1), (time.time() - t) * 1000))
            return h
        except (requests.RequestException, ValueError):
            health_ms.append((round(t - t0, 1), 5000.0))
            return None

    def prober():                      # /health latency every 0.5 s, also while the burst runs
        while not devs.stop.is_set():
            health()
            time.sleep(0.5)
    threading.Thread(target=prober, daemon=True).start()

    def watch_recovery(info, t_up):
        """After the fault ended: measure when the MEC app gets device data again and when alerts reach the
        devices again (the devices keep following the alert container, as the firmware does)."""
        info["fault_end_s"] = round(t_up - t0, 1)
        n0 = (health() or {}).get("samples", 0)
        a0 = devs.alerts
        end = time.time() + 60
        while time.time() < end and ("feed_s" not in info or "alerts_s" not in info):
            try:
                devs.subscribe_alerts()
            except Exception:
                pass
            h = health() or {}
            if "feed_s" not in info and h.get("samples", 0) > n0 + 20:
                info["feed_s"] = round(time.time() - t_up, 1)
            if "alerts_s" not in info and devs.alerts > a0:
                info["alerts_s"] = round(time.time() - t_up, 1)
            time.sleep(1.0)

    while time.time() - t0 < total:
        el = time.time() - t0
        if "burst" not in done and el >= plan["burst"]:
            done.add("burst")
            events.append({"t": round(el, 1), "event": "burst start"})
            r = burst()
            events.append({"t": round(time.time() - t0, 1), "event": "burst end", **r})
        if "churn" not in done and el >= plan["churn"]:
            done.add("churn")
            devs.churn.set()
            events.append({"t": round(el, 1), "event": "camera churn start"})
            threading.Timer(30.0, lambda: (devs.churn.clear(), events.append({"t": round(time.time() - t0, 1),
                                                                               "event": "camera churn end"}))).start()
        if "outage" not in done and el >= plan["outage"]:
            done.add("outage")
            events.append({"t": round(el, 1), "event": "link to the CSE cut"})
            proxy.stop()
            time.sleep(10.0)
            proxy.start()
            t_up = time.time()
            events.append({"t": round(t_up - t0, 1), "event": "link restored"})
            threading.Thread(target=watch_recovery, args=(recovery["outage"], t_up), daemon=True).start()
        if "reset" not in done and el >= plan["reset"]:
            done.add("reset")
            events.append({"t": round(el, 1), "event": "CSE state lost (all AEs, containers, subscriptions deleted)"})
            for rn in [cfg["ae"]] + WORKERS + FORKLIFTS + [CAMERA]:
                try:
                    admin.delete(rn)
                except Exception:
                    pass
            t_up = time.time()
            threading.Thread(target=watch_recovery, args=(recovery["reset"], t_up), daemon=True).start()
        h = health()
        rss, thr = proc_stats(mec.pid)
        with devs.lock:
            alerts = devs.alerts
        samples.append({"t": round(time.time() - t0, 1), "rss_mb": None if rss is None else round(rss, 1), "threads": thr,
                        "alive": mec.poll() is None, "health_ms": round(health_ms[-1][1], 1),
                        "samples": (h or {}).get("samples"), "tracks": (h or {}).get("tracks"),
                        "tables": (h or {}).get("tables"), "loops": (h or {}).get("loops"),
                        "degraded": (h or {}).get("degraded"), "publisher": (h or {}).get("publisher"),
                        "alerts_at_devices": alerts})
        time.sleep(2.0)
    devs.stop.set()
    time.sleep(1.0)
    final = health() or {}
    alive = mec.poll() is None
    mec.send_signal(signal.SIGTERM)
    try:
        mec.wait(10)
    except subprocess.TimeoutExpired:
        mec.kill()
    logtxt = open(log_path).read()

    # --- evaluation -------------------------------------------------------------------------------------
    warm = [s for s in samples if s["t"] >= 0.15 * total and s["rss_mb"]]
    rss0 = warm[0]["rss_mb"] if warm else None
    rss_end = samples[-1]["rss_mb"]
    normal = [l for t, l in devs.lat if t - t0 < plan["burst"]]
    t_after = plan["reset"] + recovery["reset"].get("alerts_s", 0) + 10
    after = [l for t, l in devs.lat if t - t0 > t_after]
    p95 = lambda xs: round(sorted(xs)[int(0.95 * (len(xs) - 1))], 1) if xs else None     # noqa: E731
    gc_s = cfg["mec"].get("track_gc_s", 30.0)           # forgotten after gc_s of silence, swept every 10 s
    win = [s for s in samples if s["t"] > plan["churn"] + 30 + gc_s + 12]
    max_tracks_after = max((s["tracks"] or 0) for s in win) if win else None
    tables_end = final.get("tables") or {}
    loops_dead = sorted(k for k, v in (final.get("loops") or {}).items() if not v.get("alive", True))
    checks = {
        "MEC app process stayed up for the whole run": alive and all(s["alive"] for s in samples),
        "/health always answered within 1 s (also during the burst)": max(m for _, m in health_ms) < 1000,
        "burst of 2,000 notifications (a third malformed) answered 200 every time":
            next((e for e in events if e["event"] == "burst end"), {}).get("errors", 1) == 0,
        "no unhandled exception in the MEC app (CSE error texts quoted in warnings excluded)":
            not re.search(r"^Traceback|loop \w+ failed", logtxt, re.M),
        "every background loop alive at the end": not loops_dead and bool(final.get("loops")),
        "memory growth after warm-up under 40 MB": rss0 is not None and rss_end is not None and rss_end - rss0 < 40,
        "untagged camera tracks forgotten again after the churn (tracks back to the 9 devices)":
            max_tracks_after is not None and max_tracks_after <= len(WORKERS) + len(FORKLIFTS) + 3,
        "internal tables bounded after the churn (cues, zone timers)":
            bool(tables_end) and max(tables_end.values()) <= 3 * (len(WORKERS) + len(FORKLIFTS)) + 10,
        "alerts reached the devices end to end (p95 under 500 ms in normal operation)": bool(normal) and p95(normal) < 500,
    }
    o, r = recovery["outage"], recovery["reset"]
    checks.update({
        "10 s link outage: device data back within 10 s of the link": o.get("feed_s", 1e9) <= 10,
        "10 s link outage: alerts reach the devices again within 10 s": o.get("alerts_s", 1e9) <= 10,
        "CSE state lost: the MEC app rebuilt its tree, data back within 20 s": r.get("feed_s", 1e9) <= 20,
        "CSE state lost: alerts reach the devices again within 25 s": r.get("alerts_s", 1e9) <= 25,
        "after recovery alerts are as fast as before (p95 under 500 ms)": bool(after) and p95(after) < 500,
    })
    report = {"minutes": a.minutes, "devices": {"workers": len(WORKERS), "forklifts": len(FORKLIFTS), "hz": a.hz},
              "published": {"ok": devs.pub_ok, "failed": devs.pub_fail}, "alerts_at_devices": devs.alerts,
              "alert_latency_ms": {"normal_p50": round(statistics.median(normal), 1) if normal else None, "normal_p95": p95(normal),
                                   "after_recovery_p95": p95(after)},
              "recovery": recovery, "devices_reregistered": devs.reregistered, "events": events,
              "rss_mb": {"after_warmup": rss0, "end": rss_end, "max": max((s["rss_mb"] or 0) for s in samples)},
              "threads_max": max((s["threads"] or 0) for s in samples), "health_ms_max": round(max(m for _, m in health_ms), 1),
              "health_ms_slowest": sorted(health_ms, key=lambda x: -x[1])[:5],
              "final_health": {k: final.get(k) for k in ("samples", "tracks", "tables", "loops", "publisher", "cloud", "recovery", "input", "gc")},
              "timeline": samples, "checks": checks}
    json.dump(report, open(os.path.join(ROOT, a.out), "w"), indent=1, default=str)
    print(f"published {devs.pub_ok} (failed {devs.pub_fail}), alerts at devices {devs.alerts}, "
          f"latency p95 {report['alert_latency_ms']}, rss {report['rss_mb']}, threads max {report['threads_max']}, "
          f"/health max {report['health_ms_max']} ms, recovery {recovery}")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=soak::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v],
         "recovery": recovery, "rss_mb": report["rss_mb"], "latency": report["alert_latency_ms"]}))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("::error title=soak_test::" + " | ".join(traceback.format_exc().strip().splitlines()[-6:])[:1500])
        raise
