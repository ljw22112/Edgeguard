"""Federated learning whose clients are deployed by the oneM2M orchestrator, on an ACME CSE.

    scripts/acme.sh start in
    python tools/fl_deploy_demo.py                     # instances in-process
    python tools/fl_deploy_demo.py --runtime docker    # one container per FL client (deploy/edge-app)

The full FL lifecycle of TR-0077 7.3 / TR-0084, every step through oneM2M resources:

  intent    the operator creates one egs:depIn per site (app edgeguard-fl, zone = site)
  deploy    the orchestrator places each on that site's MEC host, the instance registers and is provisioned
            with its site (edgeguard/fl_app.py)
  discover  the coordinator finds the deployed clients by label (egs:fl/participant)
  train     rounds: selection, local training on the host's own data, FedAvg of weights only
  aggregate model versions with lineage in EdgeGuardFL/models
  infer     every client evaluates each new model on its site's held-out data and reports it in its heartbeat

Round 3: the Incheon MEC host crashes while training (dropout).  Its participant stops refreshing and is no
longer selected; the orchestrator does not move the client to another site, because the data is on that host.
Round 4: the operator adds Daejeon with one more intent; the new client joins the next round.
Result: results/fl_deploy.json (results/fl_deploy_docker.json with --runtime docker).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard import fl                                                     # noqa: E402
from edgeguard.onem2m import OneM2MClient, OneM2MError, parse_notification  # noqa: E402
from edgeguard.orchestration import ORCH_AE, MecHostAgent, Orchestrator, submit_intent   # noqa: E402

CSE = ("http://127.0.0.1:8080", "cse-in")
ORCH, OPERATOR, PORT = "SEGOrch", "COperator", 9350
SITES = ["seoul", "busan", "incheon", "daejeon"]
ROUNDS = 6


def build_image(image, base):
    ctx = tempfile.mkdtemp(prefix="egfl")
    os.makedirs(os.path.join(ctx, "edgeguard"))
    for f in ("__init__.py", "onem2m.py", "orchestration.py", "edge_app.py", "fl.py", "fl_app.py"):
        shutil.copy(os.path.join(ROOT, "edgeguard", f), os.path.join(ctx, "edgeguard", f))
    shutil.copy(os.path.join(ROOT, "deploy", "edge-app", "Dockerfile"), os.path.join(ctx, "Dockerfile"))
    r = subprocess.run(["docker", "build", "-q", "-t", image, "--build-arg", f"BASE={base}", ctx], capture_output=True, text=True)
    shutil.rmtree(ctx, ignore_errors=True)
    if r.returncode != 0:
        raise SystemExit(f"::error title=fl_deploy::docker build failed: {r.stderr.strip()[-400:]}")


def containers():
    r = subprocess.run(["docker", "ps", "--filter", "label=edgeguard.app=edgeguard-fl", "--format", '{{.Label "edgeguard.host"}}'],
                       capture_output=True, text=True)
    return sorted(x for x in r.stdout.split() if x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", choices=("thread", "docker"), default="thread")
    ap.add_argument("--image", default="edgeguard/edge-app:1.0")
    ap.add_argument("--base", default="python:3.11-slim")
    a = ap.parse_args()
    if a.runtime == "docker":
        subprocess.run(["bash", "-c", "docker rm -f $(docker ps -aq --filter label=edgeguard.app) 2>/dev/null"], capture_output=True)
        build_image(a.image, a.base)
    admin = OneM2MClient(*CSE, "CAdmin")
    for rn in ([ORCH_AE, fl.COORD] + [f"host-{s}" for s in SITES] + [f"fl_{s}" for s in SITES]
               + admin.discover_label("egs:app/edgeguard-fl", ty=2)):
        admin.delete(rn)

    # --- the coordinator (IN-CSE) -------------------------------------------------------------------------
    url = f"http://127.0.0.1:{PORT}"
    coord = fl.Coordinator(OneM2MClient(*CSE, "SEdgeGuardFL"), f"{url}/coord", rounds=ROUNDS, cpr=3, quorum=2,
                           min_samples=1000, local_epochs=8, timeout=8.0, log=lambda *x: None, stale_s=3.0)

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self.send_response(200)
            self.send_header("X-M2M-RSC", "2000")
            self.end_headers()
            kind, con = parse_notification(body)
            if kind == "cin" and isinstance(con, dict) and self.path.startswith("/coord/"):
                coord.on_update(self.path.rsplit("/", 1)[1], con)

        def log_message(self, *x):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    coord.setup()

    # --- one MEC host per site, the orchestrator -----------------------------------------------------------
    hosts = {}
    for i, s in enumerate(SITES):
        hosts[s] = MecHostAgent(CSE, f"host-{s}", s, 4, 4096, 2.0, 9451 + i, range(9460 + 10 * i, 9470 + 10 * i),
                                runtime=a.runtime, image=a.image).start(readers=[ORCH])
    orch = Orchestrator(CSE, ORCH, operators=[OPERATOR], log=(print if os.environ.get("ORCH_DEBUG") else lambda *x: None)).setup()
    time.sleep(1.2)
    op = OneM2MClient(*CSE, OPERATOR)

    def wait(pred, timeout):
        end = time.time() + timeout
        while time.time() < end and not pred():
            time.sleep(0.1)
        return pred()

    def running(rn):
        return any(e["intent"] == f"intent_fl-{rn}" and e["step"] == "running" for e in orch.events)

    def participants():
        return sorted(p["ae"] for p in coord.participants())

    t0 = time.time()
    for s in ("seoul", "busan", "incheon"):                       # intent
        submit_intent(op, f"fl-{s}", "edgeguard-fl", zone=s, cpu=1, mem=512, max_latency=10)
    wait(lambda: all(running(s) for s in ("seoul", "busan", "incheon")), 40)
    wait(lambda: len(participants()) >= 3, 15)                     # discover
    t_ready = time.time() - t0
    placed = {s: orch.intents.get(f"intent_fl-{s}", {}).get("host") for s in ("seoul", "busan", "incheon")}
    found_initial = participants()
    ctr_initial = containers() if a.runtime == "docker" else None

    # --- train / aggregate ----------------------------------------------------------------------------------
    events, r = [], 1
    while len([h for h in coord.history if h.get("aggregated")]) < ROUNDS and r <= 3 * ROUNDS:
        if r == 3:     # the Incheon host dies as round 3 starts: its participant still looks fresh, so it is selected
            hosts["incheon"].crash()
            events.append("round 3: host-incheon crashes (selected, never answers)")
        if r == 4:
            submit_intent(op, "fl-daejeon", "edgeguard-fl", zone="daejeon", cpu=1, mem=512, max_latency=10)
            events.append("round 4: operator submits the Daejeon intent")
        coord.run_round(r)
        if r == 4:                                                 # the new site is deployed while round 4 trains
            wait(lambda: "fl_daejeon" in participants(), 20)
        r += 1
    coord.c.update_fcnt(f"{fl.COORD}/task", "egs:flTsk", {"tskSt": "done"})
    wait(lambda: orch.intents.get("intent_fl-incheon", {}).get("status") in ("unschedulable",), 15)

    # --- infer: every live client reports the final model on its own held-out data ------------------------------
    def status(site):
        ae = orch.intents.get(f"intent_fl-{site}", {}).get("app_ae")
        try:
            con = admin.request("GET", f"{ae}/status/la")["m2m:cin"]["con"]
            return (json.loads(con) if isinstance(con, str) else con).get("fl") or {}
        except (OneM2MError, TypeError, ValueError):
            return {}
    live = ("seoul", "busan", "daejeon")
    wait(lambda: all(status(s).get("model_version") == coord.version for s in live), 10)
    infer = {s: status(s) for s in live}
    ctr_final = containers() if a.runtime == "docker" else None
    orch.stop.set()

    # --- evaluation ---------------------------------------------------------------------------------------
    hist = coord.history
    steps = {s: [e["step"] for e in orch.events if e["intent"] == f"intent_fl-{s}"] for s in SITES}
    inc_events = [e for e in orch.events if e["intent"] == "intent_fl-incheon"]
    upd = []
    for s in SITES:
        for u in admin.discover(f"fl_{s}/updates", ty=4):
            con = admin.request("GET", u)["m2m:cin"]["con"]
            upd.append(json.loads(con) if isinstance(con, str) else con)
    n_params = fl.N_IN * fl.N_HID + fl.N_HID + fl.N_HID * fl.N_OUT + fl.N_OUT
    task = admin.request("GET", f"{fl.COORD}/task")["egs:flTsk"]
    checks = {
        "intent -> deploy: each FL client placed on its own site's MEC host":
            placed == {s: f"host-{s}" for s in ("seoul", "busan", "incheon")},
        "lifecycle per intent: selected -> deployed -> registered -> provisioned -> running":
            all(steps[s][:6] == ["accepted", "selected", "deployed", "registered", "provisioned", "running"]
                for s in ("seoul", "busan", "incheon", "daejeon")),
        "discover: the coordinator found the deployed clients by label": found_initial == ["fl_busan", "fl_incheon", "fl_seoul"],
        f"train / aggregate: {ROUNDS} model versions, task done":
            task.get("tskSt") == "done" and task.get("mdlVr") == coord.version == ROUNDS,
        "dropout: host-incheon crashed at round 3, the round aggregated with the quorum":
            any(h["round"] == 3 and h["aggregated"] and "fl_incheon" in h["dropped"] for h in hist),
        "liveness: Incheon never selected after its host died":
            all("fl_incheon" not in h["selected"] for h in hist if h["round"] > 3),
        "data residency: the Incheon client was not moved to another site; updates carry only weights":
            any(e["step"] == "host_lost" for e in inc_events) and inc_events[-1]["step"] == "unschedulable"
            and all(set(u) <= {"round", "n", "weights", "loss", "base_version"} and len(fl.base64.b64decode(u["weights"])) == 4 * n_params
                    for u in upd),
        "late join: the Daejeon intent was deployed and its client selected in a later round":
            running("daejeon") and any("fl_daejeon" in h["selected"] for h in hist if h["round"] >= 5),
        "infer at the edge: every live client runs the final model and beats constant velocity on its own data":
            all(infer[s].get("model_version") == coord.version and infer[s].get("ade_2s", 9) < infer[s].get("cv_2s", 0)
                for s in live),
    }
    if a.runtime == "docker":
        checks["each FL client ran as its own container on its site's host"] = (
            ctr_initial == ["host-busan", "host-incheon", "host-seoul"] and ctr_final == ["host-busan", "host-daejeon", "host-seoul"])
    report = {"runtime": a.runtime, "placement": placed, "ready_s": round(t_ready, 2), "rounds": hist, "events": events,
              "inference": infer, "containers": {"initial": ctr_initial, "final": ctr_final},
              "orchestration": [{**e, "t": round(e["t"] - t0, 3)} for e in orch.events], "checks": checks}
    out = "fl_deploy.json" if a.runtime == "thread" else "fl_deploy_docker.json"
    json.dump(report, open(os.path.join(ROOT, "results", out), "w"), indent=1, default=str)
    for h in hist:
        print(f"  round {h['round']}: selected {h['selected']} received {h['received']} -> v{h['version']}")
    print(f"  ready after {t_ready:.1f} s; inference {infer}")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    for s, h in hosts.items():
        if s != "incheon":
            h.crash()
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + f" title=fl_deploy ({a.runtime})::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v],
         "placement": placed, "inference": infer}))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("::error title=fl_deploy_demo::" + " | ".join(traceback.format_exc().strip().splitlines()[-6:])[:1500])
        raise
