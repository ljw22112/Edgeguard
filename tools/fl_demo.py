"""Federated learning through oneM2M (edgeguard/fl.py), end to end on an ACME CSE.

    scripts/acme.sh start in
    python tools/fl_demo.py

Three sites start (Seoul, Busan, Incheon); Incheon goes offline during round 3 (dropout); Daejeon
registers before round 4 (late join, found by label discovery).  Each client trains on its own walking
data; only weights travel through oneM2M.  Afterwards: the global model against constant velocity and
against each site's model trained alone, on every site's held-out data.  Result: results/fl.json
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
from edgeguard import fl                                       # noqa: E402
from edgeguard.onem2m import OneM2MClient, parse_notification  # noqa: E402

CSE = ("http://127.0.0.1:8080", "cse-in")
PORT = 9320
SIZES = {"seoul": 1200, "busan": 1200, "incheon": 240, "daejeon": 600}     # seconds of walking data per site


def main():
    data = {s: fl.site_data(s, sec, seed=i) for i, (s, sec) in enumerate(SIZES.items())}
    test = {s: fl.site_data(s, 600, seed=100 + i) for i, s in enumerate(SIZES)}
    url = f"http://127.0.0.1:{PORT}"
    coord = fl.Coordinator(OneM2MClient(*CSE, "SEdgeGuardFL"), f"{url}/coord", rounds=6, cpr=3, quorum=2,
                           min_samples=1000, local_epochs=8, timeout=6.0)
    clients = {s: fl.Client(OneM2MClient(*CSE, f"Sfl{s}"), s, *data[s], f"{url}/client/{s}",
                            compute={"seoul": 1.0, "busan": 0.8, "incheon": 0.5, "daejeon": 0.9}[s]) for s in SIZES}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            self.send_response(200)
            self.send_header("X-M2M-RSC", "2000")
            self.end_headers()
            kind, con = parse_notification(body)
            if kind != "cin" or not isinstance(con, dict):
                return
            if self.path.startswith("/coord/"):          # one notification URL per participant
                coord.on_update(self.path.rsplit("/", 1)[1], con)
            elif self.path.startswith("/client/"):
                clients[self.path.rsplit("/", 1)[1]].on_round(con)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    coord.setup()
    for s in ("seoul", "busan", "incheon"):
        clients[s].register()
    clients["daejeon"].c.delete("fl_daejeon")
    events = []
    r = 1
    while len([h for h in coord.history if h.get("aggregated")]) < coord.cfg["rounds"] and r <= 18:
        if r == 3:                                   # Incheon drops out right after being selected
            clients["incheon"].crash_next = True
            events.append("round 3: incheon goes offline after selection")
        if r == 4:                                   # a new site registers itself
            clients["daejeon"].register()
            events.append("round 4: daejeon registers (label discovery)")
        if r == 6:
            clients["incheon"].set_online(True)
            events.append("round 6: incheon back online")
        coord.run_round(r)
        r += 1
    coord.c.update_fcnt(f"{fl.COORD}/task", "egs:flTsk", {"tskSt": "done"})
    w = coord.w

    # --- evaluation ---------------------------------------------------------------------------
    def ade_all(wt):
        return {s: round(fl.ade(wt, *test[s]), 3) for s in test}
    cv = ade_all(None)
    glob = ade_all(w)
    rounds_total = 8 * coord.cfg["rounds"]
    local = {s: ade_all(fl.train(fl.init_weights(0), *data[s], epochs=rounds_total)[0]) for s in SIZES}
    local_cross = {s: round(float(np.mean(list(v.values()))), 3) for s, v in local.items()}
    mean = lambda d: round(float(np.mean(list(d.values()))), 3)     # noqa: E731

    # --- checks -----------------------------------------------------------------------------------
    c = coord.c
    task = c.request("GET", f"{fl.COORD}/task")["egs:flTsk"]
    models = [c.request("GET", u) for u in c.discover(f"{fl.COORD}/models", ty=4)]
    models = [fl.json.loads(m["m2m:cin"]["con"]) if isinstance(m["m2m:cin"]["con"], str) else m["m2m:cin"]["con"]
              for m in models]
    hist = coord.history
    upd_payloads = []
    for s in SIZES:
        for u in c.discover(f"fl_{s}/updates", ty=4):
            con = c.request("GET", u)["m2m:cin"]["con"]
            upd_payloads.append(json.loads(con) if isinstance(con, str) else con)
    n_params = fl.N_IN * fl.N_HID + fl.N_HID + fl.N_HID * fl.N_OUT + fl.N_OUT
    raw_keys = {"x", "y", "track", "X", "Y", "positions", "samples"}
    checks = {
        "task resource tracks the run (status done, model version = aggregated rounds)":
            task.get("tskSt") == "done" and task.get("mdlVr") == coord.version == coord.cfg["rounds"],
        "dynamic selection: participants found by label, offline client never selected while offline":
            all("fl_incheon" not in h["selected"] for h in hist if 3 < h["round"] < 6),
        "dropout tolerated: round 3 aggregated with the quorum":
            any(h["round"] == 3 and h["aggregated"] and "fl_incheon" in h["dropped"] for h in hist),
        "late join: daejeon selected after it registered": any("fl_daejeon" in h["selected"] for h in hist if h["round"] >= 4),
        "data stays local: updates carry only weights (no positions)":
            all(not (raw_keys & set(p)) and len(fl.base64.b64decode(p["weights"])) == 4 * n_params for p in upd_payloads),
        "model lineage: every version published with parent and participants":
            sorted(m["version"] for m in models) == list(range(coord.version + 1))
            and all(m["participants"] for m in models if m["version"] > 0),
        "global model beats constant velocity on every site": all(glob[s] < cv[s] for s in SIZES),
        "global model generalises better than models trained alone (mean over all sites)":
            mean(glob) < float(np.mean(list(local_cross.values()))),
    }
    report = {"rounds": hist, "events": events, "ade_2s_m": {"constant_velocity": cv, "federated_global": glob,
              "local_only_on_all_sites_mean": local_cross}, "mean_ade_2s_m": {"constant_velocity": mean(cv),
              "federated_global": mean(glob), "local_only_mean": round(float(np.mean(list(local_cross.values()))), 3)},
              "update_bytes": 4 * n_params, "checks": checks}
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(report, open(os.path.join(ROOT, "results", "fl.json"), "w"), indent=1)
    print(f"2 s prediction error (mean over 4 sites): constant velocity {mean(cv)} m, federated {mean(glob)} m, "
          f"each site alone {report['mean_ade_2s_m']['local_only_mean']} m")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=fl::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "ade": report["mean_ade_2s_m"]}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
