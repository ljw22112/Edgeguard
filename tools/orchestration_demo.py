"""MEC application orchestration through oneM2M (edgeguard/orchestration.py), on an ACME CSE.

    scripts/acme.sh start in
    python tools/orchestration_demo.py

Three MEC hosts register themselves (zone A edge host, a smaller second zone A host, a regional cloud
host 25 ms away).  An operator submits three deployment intents as oneM2M resources: the EdgeGuard risk
engine for zone A (2 CPU, <= 10 ms), the site analytics (8 CPU, <= 100 ms, any zone) and an impossible one
(64 CPU).  The orchestrator discovers, selects, deploys, waits for the instance to register, provisions it
(device ACP + configuration) and confirms it runs - the deployed risk engine then processes a forklift's
live data.  Then the zone A edge host crashes: the risk engine is re-placed on the second zone A host
and keeps processing.  Result: results/orchestration.json
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.onem2m import ALL_OPS, OneM2MClient, OneM2MError   # noqa: E402
from edgeguard.orchestration import ORCH_AE, INTENT_TP, MecHostAgent, Orchestrator, submit_intent   # noqa: E402

CSE = ("http://127.0.0.1:8080", "cse-in")
ORCH, OPERATOR, DEV_ORIGIN = "SEGOrch", "COperator", "Cfkorch"
HOSTS = [("host-a1", "A", 4, 4096, 2.0, 9401), ("host-a2", "A", 2, 2048, 4.0, 9402), ("host-cloud", "", 16, 32768, 25.0, 9403)]


def main():
    admin = OneM2MClient(*CSE, "CAdmin")
    for rn in [ORCH_AE, "fk_orch"] + [h[0] for h in HOSTS] + [a for a in (admin.discover_label("egs:app/edgeguard-risk", ty=2)
                                                                          + admin.discover_label("egs:app/site-analytics", ty=2))]:
        admin.delete(rn)

    # a forklift publishing 5 samples/s; its ACP lists the orchestrator as an owner (it may grant apps access)
    dev = OneM2MClient(*CSE, DEV_ORIGIN)
    dev.create_ae("fk_orch", api="Nedgeguard.forklift")
    dev.create_container("fk_orch", "motion", mni=50)
    acp = dev.create_acp("fk_orch", "acp_fk", [([DEV_ORIGIN], ALL_OPS)], [DEV_ORIGIN, ORCH])
    dev.set_acpi("fk_orch/motion", "fk_orch/acp_fk", acp.get("ri"))
    stop = threading.Event()

    def drive():
        i = 0
        while not stop.wait(0.2):
            try:
                dev.create_cin("fk_orch/motion", {"seq": i, "x": i * 0.4, "y": 2.0})
            except Exception:
                pass
            i += 1
    threading.Thread(target=drive, daemon=True).start()

    hosts = {}
    for i, (name, zone, cpu, mem, rtt, port) in enumerate(HOSTS):
        hosts[name] = MecHostAgent(CSE, name, zone, cpu, mem, rtt, port, range(9410 + 10 * i, 9420 + 10 * i)).start(readers=[ORCH])
    orch = Orchestrator(CSE, ORCH, operators=[OPERATOR], log=(print if os.environ.get("ORCH_DEBUG") else lambda *a: None),
                        bindings={"edgeguard-risk": [{"path": "fk_orch/motion", "acp": "fk_orch/acp_fk"}]}).setup()
    time.sleep(1.2)

    op = OneM2MClient(*CSE, OPERATOR)
    t_submit = time.time()
    submit_intent(op, "risk", "edgeguard-risk", zone="A", cpu=2, mem=512, max_latency=10)
    submit_intent(op, "analytics", "site-analytics", cpu=8, mem=4096, max_latency=100)
    submit_intent(op, "huge", "edgeguard-risk-xl", zone="A", cpu=64, mem=1024, max_latency=10)

    def wait(pred, timeout):
        end = time.time() + timeout
        while time.time() < end and not pred():
            time.sleep(0.1)
        return pred()

    def status(rn):
        return orch.intents.get(f"intent_{rn}", {}).get("status")
    ran = lambda rn: any(e["intent"] == rn and e["step"] == "running" for e in orch.events)   # noqa: E731
    wait(lambda: ran("intent_risk") and ran("intent_analytics") and status("huge") == "unschedulable", 15)
    t_running = {e["intent"]: e["t"] - t_submit for e in orch.events if e["step"] == "running"}
    placed1 = {rn: orch.intents.get(f"intent_{rn}", {}).get("host") for rn in ("risk", "analytics")}
    risk_ae1 = orch.intents["intent_risk"].get("app_ae")
    time.sleep(2.5)
    proc1 = hosts["host-a1"].instances and max(a.processed for a, _ in hosts["host-a1"].instances.values())
    intent_res = op.request("GET", f"{ORCH_AE}/intent_risk")[INTENT_TP]
    old_origin = orch.intents["intent_risk"].get("app_origin")

    # --- the zone A edge host crashes --------------------------------------------------------------------
    t_crash = time.time()
    hosts["host-a1"].crash()
    # wait for the "running" event itself: the intent's status is written just before the event is recorded
    wait(lambda: any(e["intent"] == "intent_risk" and e["step"] == "running" and e.get("reason") == "host_lost"
                     for e in orch.events), 20)
    rec = next((e for e in orch.events if e["intent"] == "intent_risk" and e["step"] == "running" and e.get("reason") == "host_lost"), None)
    detect = next((e for e in orch.events if e["step"] == "host_lost"), None)
    time.sleep(2.5)
    a2 = [a for a, _ in hosts["host-a2"].instances.values() if a.name == "edgeguard-risk"]
    proc2 = a2[0].processed if a2 else 0
    acp_after = admin.request("GET", "fk_orch/acp_fk")["m2m:acp"]["pv"]["acr"]
    revoked = not any(old_origin in r["acor"] for r in acp_after)
    try:
        OneM2MClient(*CSE, old_origin).request("GET", "fk_orch/motion/la")
        old_blocked = False
    except OneM2MError as e:
        old_blocked = e.status == 403
    try:
        OneM2MClient(*CSE, "CIntruder").create_fcnt(ORCH_AE, INTENT_TP, "intent_evil", "x", {"appNm": "evil"})
        intruder_blocked = False
    except OneM2MError as e:
        intruder_blocked = e.status == 403
    stop.set()
    orch.stop.set()
    steps = [e["step"] for e in orch.events if e["intent"] == "intent_risk"]

    checks = {
        "hosts registered themselves in oneM2M and were found by label discovery": len(orch.hosts()) >= 2,
        "risk engine (zone A, <= 10 ms) placed on the zone A edge host": placed1["risk"] == "host-a1",
        "analytics (8 CPU, <= 100 ms) placed on the cloud host": placed1["analytics"] == "host-cloud",
        "impossible intent reported unschedulable, nothing deployed": status("huge") == "unschedulable",
        "full lifecycle recorded: selected -> deployed -> registered -> provisioned -> running":
            steps[:5] == ["accepted", "selected", "deployed", "registered", "provisioned"] and "running" in steps,
        "intent resource shows status, placement and the instance's AE":
            intent_res.get("intSt") == "running" and intent_res.get("plcmt") == "host-a1" and intent_res.get("appAe") == risk_ae1,
        "deployed risk engine processes the forklift's live data (provisioned subscription)": bool(proc1) and proc1 > 3,
        "host crash detected and the risk engine re-placed on host-a2": rec is not None and placed1["risk"] == "host-a1",
        "re-placed instance processes live data again": proc2 > 3,
        "old instance's access revoked from the device ACP": revoked and old_blocked,
        "only operators may submit intents (ACP)": intruder_blocked,
    }
    report = {"placement": placed1, "time_to_running_s": {k: round(v, 2) for k, v in t_running.items()},
              "recovery": {"detect_s": round(detect["t"] - t_crash, 2) if detect else None,
                           "running_again_s": round(rec["t"] - t_crash, 2) if rec else None,
                           "new_host": orch.intents["intent_risk"].get("host")},
              "processed": {"before_crash": proc1, "after_recovery": proc2},
              "events": [{**e, "t": round(e["t"] - t_submit, 3)} for e in orch.events], "checks": checks}
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(report, open(os.path.join(ROOT, "results", "orchestration.json"), "w"), indent=1, default=str)
    print(f"placement {placed1}; running after {report['time_to_running_s']} s; host crash -> running again on "
          f"{report['recovery']['new_host']} after {report['recovery']['running_again_s']} s")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    for h in hosts.values():
        if h.name != "host-a1":
            h.crash()
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=orchestration::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v], "placement": placed1, "recovery": report["recovery"]}))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("::error title=orchestration_demo::" + " | ".join(traceback.format_exc().strip().splitlines()[-6:])[:1500])
        raise
