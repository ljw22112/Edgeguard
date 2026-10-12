"""Federated model delivery to a site's MEC app: canary, activate, monitor, roll back (edgeguard/model_delivery.py).

    scripts/acme.sh start in
    python tools/model_delivery_demo.py

The FL coordinator publishes model versions through oneM2M; the Busan site's model manager is subscribed:
  v0  untrained initial weights                       -> rejected by the canary (worse than constant velocity)
  v1  global model from all four sites                -> activated
  v2  corrupted update (weights blown up)             -> rejected
  v3  specialised on Busan's own aisles               -> activated (better on Busan's held-out data)
Then the site's layout changes (narrow aisles, frequent stops, as in Incheon): live monitoring sees v3 lose
to the shadow-evaluated v1 and rolls back.  The risk engine (method guidance_fl) predicts with whatever is
active.  Result: results/model_delivery.json
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard import fl                                                     # noqa: E402
from edgeguard.model_delivery import REGISTRY, ModelManager                  # noqa: E402
from edgeguard.onem2m import OneM2MClient, parse_notification               # noqa: E402
from edgeguard.risk import RiskConfig, assess                               # noqa: E402
from edgeguard.tracking import Track                                         # noqa: E402

CSE = ("http://127.0.0.1:8080", "cse-in")
PORT = 9340
SITE_AE, SITE_ORIGIN = "site_busan", "Sflsitebusan"


def worker_track(walk, t0=0.0):
    tr = Track("worker_01", "worker")
    for i, (x, y) in enumerate(walk):
        tr.update(t0 + i * 0.1, float(x), float(y))
    return tr


def main():
    t_all = time.time()
    data = {s: fl.site_data(s, 600, seed=i) for i, s in enumerate(fl.SITES)}
    X = np.concatenate([d[0] for d in data.values()])
    Y = np.concatenate([d[1] for d in data.values()])
    w_global, _ = fl.train(fl.init_weights(0), X, Y, epochs=12)
    w_busan, _ = fl.train(fl.init_weights(0), *fl.site_data("busan", 1200, seed=11), epochs=40)
    w_bad = {k: v * 6.0 for k, v in w_global.items()}
    holdout = fl.site_data("busan", 300, seed=50)

    admin = OneM2MClient(*CSE, "CAdmin")
    admin.delete(SITE_AE)
    coord = fl.Coordinator(OneM2MClient(*CSE, "SEdgeGuardFL"), f"http://127.0.0.1:{PORT}/coord", rounds=1)
    REGISTRY.set(None, None)
    mgr = ModelManager(OneM2MClient(*CSE, SITE_ORIGIN), SITE_AE, holdout, log=lambda *a: None)
    decisions, lock = [], threading.Event()

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self.send_response(200)
            self.send_header("X-M2M-RSC", "2000")
            self.end_headers()
            kind, con = parse_notification(body)
            if self.path == "/site" and kind == "cin" and isinstance(con, dict) and "weights" in con:
                decisions.append((con["version"], mgr.on_model(con)))
                lock.set()

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    coord.setup()                                   # publishes v0 (initial weights) before the site subscribes
    mgr.setup()
    OneM2MClient(*CSE, SITE_ORIGIN).create_subscription(f"{fl.COORD}/models", "sub_site", [f"http://127.0.0.1:{PORT}/site"])
    la = OneM2MClient(*CSE, SITE_ORIGIN).latest(f"{fl.COORD}/models")     # catch up with the current version
    decisions.append((la["version"], mgr.on_model(la)))

    def publish(w):
        lock.clear()
        coord.version += 1
        coord.w = w
        t0 = time.time()
        coord._publish_model(round_=coord.version, participants=["fl_seoul", "fl_busan", "fl_incheon", "fl_daejeon"], metrics={})
        lock.wait(10)
        return round((time.time() - t0) * 1000, 1)
    delivery_ms = [publish(w_global), publish(w_bad), publish(w_busan)]
    active_before = REGISTRY.get()[0]

    # the risk engine predicts with the active model
    cfg = RiskConfig()
    rng = np.random.default_rng(7)
    walk = fl.walk("busan", 6.0, rng)
    w_tr = worker_track(walk)
    f_tr = Track("forklift_01", "forklift")
    for i in range(10):
        f_tr.update(i * 0.1 + len(walk) * 0.1 - 1.0, float(walk[-1][0]) + 8.0 - 0.2 * i, float(walk[-1][1]))
    uses0 = REGISTRY.uses
    r = assess(w_tr, f_tr, cfg, method="guidance_fl")
    engine_used = REGISTRY.uses > uses0

    # layout change: live windows look like Incheon now
    live = []
    for k in range(5):
        Xl, Yl = fl.site_data("incheon", 120, seed=200 + k)
        live.append(mgr.observe(Xl, Yl))
        if live[-1].get("rolled_back"):
            break
    dep = admin.request("GET", f"{SITE_AE}/model")["egs:mdlDp"]
    hist_n = len(admin.request("GET", f"{SITE_AE}/model", params={"fu": 1, "ty": 58}).get("m2m:uril", []))
    srv.shutdown()

    dec = dict(decisions)
    checks = {
        "v0 (untrained) rejected by the canary": dec.get(0) == "rejected",
        "v1 (global) activated": dec.get(1) == "active",
        "v2 (corrupted) rejected, v1 kept": dec.get(2) == "rejected",
        "v3 (site-specialised) activated, better on the site's held-out data": dec.get(3) == "active" and active_before == 3,
        "risk engine predicted with the active federated model (guidance_fl)": engine_used and r is not None,
        "after the layout change, monitoring rolled back to v1": bool(live) and live[-1].get("rolled_back") is True
            and REGISTRY.get()[0] == 1,
        "deployment status in oneM2M (egs:mdlDp): rolled_back, now v1, previous v3":
            dep.get("dplSt") == "rolled_back" and dep.get("mdlVr") == 1 and dep.get("prvVr") == 3,
        "every step kept as history (flexContainerInstances)": hist_n >= 6,
    }
    report = {"decisions": mgr.history, "delivery_ms": delivery_ms, "live_monitoring": live,
              "deployment": {k: dep.get(k) for k in ("mdlVr", "prvVr", "dplSt", "cnyEr", "bslEr", "lvErr")},
              "risk_engine_sample": {"level": r.level_name if hasattr(r, "level_name") else getattr(r, "level", None)},
              "history_entries": hist_n, "runtime_s": round(time.time() - t_all, 1), "checks": checks}
    json.dump(report, open(os.path.join(ROOT, "results", "model_delivery.json"), "w"), indent=1, default=str)
    for h in mgr.history:
        print("  ", h)
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=model_delivery::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v],
         "decisions": [(h["version"], h["decision"]) for h in mgr.history], "delivery_ms": delivery_ms}))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("::error title=model_delivery_demo::" + " | ".join(traceback.format_exc().strip().splitlines()[-6:])[:1500])
        raise
