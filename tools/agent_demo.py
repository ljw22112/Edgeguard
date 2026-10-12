"""AI safety agent with MCP servers (agent/), end to end on ACME + the MEC mock.

    scripts/acme.sh start in mn-a mn-b
    python tools/agent_demo.py

Seeds a shift: worker / forklift twins (forklift_01 served by zone B's MN-CSE after a CSE handover attach,
the others on the IN-CSE), 25 near-miss records with three real hotspots, people and radio load in the MEC
mock.  Run 1: full shift report.  Run 2: five new near misses arrive and zone B's CSE goes down - the agent
reads only the new records (state kept in oneM2M) and finishes with a partial report instead of failing.
Result: results/agent.json
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import subprocess
import sys
import threading
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from agent.safety_agent import AGENT_AE, MCPHub, SafetyAgent, default_servers   # noqa: E402
from edgeguard import sdt                                                       # noqa: E402
from edgeguard.handover import HandoverClient, setup_home                       # noqa: E402
from edgeguard.mec_services import SiteFrame                                    # noqa: E402
from edgeguard.onem2m import ALL_OPS, DISCOVERY, RETRIEVE, OneM2MClient, OneM2MError   # noqa: E402
from tools.handover_demo import ZONES                                           # noqa: E402

IN = ("http://127.0.0.1:8080", "cse-in")
MEC, AGENT, MECAPP = "http://127.0.0.1:8085", "SEdgeGuardAgent", "SEdgeGuard"
CFG = {"forklift": {"max_speed": 2.5}, "handover": {"in_cse_id": "id-in"}}
FRAME = SiteFrame(37.55, 127.07)


def ensure_mec_mock():
    try:
        requests.get(f"{MEC}/_mock/stats", timeout=1)
        return None
    except requests.RequestException:
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", "mec_mock.server:app", "--port", "8085",
                              "--log-level", "warning"], cwd=ROOT, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(40):
            try:
                requests.get(f"{MEC}/_mock/stats", timeout=1)
                return p
            except requests.RequestException:
                time.sleep(0.25)
        raise SystemExit("MEC mock did not start")


def near_miss(rng, x, y, forklift, worker, occluded=False, alerted=True, speed=1.4):
    return {"worker": worker, "forklift": forklift, "t": time.time(), "d_min": round(rng.uniform(0.6, 1.9), 2),
            "x": round(x + rng.uniform(0.05, 0.9), 2), "y": round(y + rng.uniform(0.05, 0.9), 2),
            "forklift_speed": round(speed + rng.uniform(-0.1, 0.1), 2), "occluded": occluded, "alerted": alerted}


def seed(rng):
    mec = OneM2MClient(*IN, MECAPP)
    ag = OneM2MClient(*IN, AGENT)
    admin = OneM2MClient(*IN, "CAdmin")                              # clean start (leftovers of other demos)
    for rn in ("worker_01", "worker_02", "forklift_02", "forklift_01", "EdgeGuard", AGENT_AE):
        admin.delete(rn)
    for z in ZONES:
        OneM2MClient(z.base_url, z.cse_rn, "CAdmin").delete("forklift_01")
    readers = [MECAPP, AGENT]
    for dev, kind in (("worker_01", "worker"), ("worker_02", "worker"), ("forklift_02", "forklift")):
        sdt.build_twin(OneM2MClient(*IN, "S" + dev.replace("_", "").capitalize()), CFG, dev, kind, readers,
                       log=lambda *_: None)
    home = OneM2MClient(*IN, "SForklift01")
    setup_home(home, "forklift_01", readers)
    hc = HandoverClient(CFG, "forklift_01", "forklift", "SForklift01", ZONES, home=home, readers=readers, log=lambda *_: None)
    hc.attach(10.0, 0.0)                                              # zone B
    hc.client("B").update_fcnt("forklift_01/module/speedLimit", "egs:spdLt", {"limit": 1.5})
    # the MEC app's near-miss records; the agent may read them
    mec.create_ae("EdgeGuard", "Nedgeguard.mec")
    mec.create_container("EdgeGuard", "nearmiss", mni=2000)
    acp = mec.create_acp("EdgeGuard", "acp_nearmiss", [([MECAPP], ALL_OPS), ([AGENT], RETRIEVE | DISCOVERY)], [MECAPP])
    mec.set_acpi("EdgeGuard/nearmiss", "EdgeGuard/acp_nearmiss", acp.get("ri"))
    # the agent's own AE: state, reports, run log
    ag.create_ae(AGENT_AE, "Nedgeguard.agent", lbl=["egs:agent"])
    for cnt in ("state", "reports", "runs"):
        ag.create_container(AGENT_AE, cnt, mni=200)
    events = ([near_miss(rng, 12, 4, "forklift_01", f"worker_0{1 + i % 2}", occluded=True) for i in range(9)]
              + [near_miss(rng, -7, 0, "forklift_02", "worker_02", speed=2.6) for _ in range(6)]
              + [near_miss(rng, 3, -9, "forklift_02", "worker_01") for _ in range(4)]
              + [near_miss(rng, rng.uniform(-20, 20), rng.uniform(-10, 10), "forklift_02", "worker_01") for _ in range(6)])
    for e in events:
        mec.create_cin("EdgeGuard/nearmiss", e)
    return mec, hc


def people_feed(stop):
    """People the network locates right now: three near the blind corner, one at the fast crossing."""
    spots = {"acr:10.0.0.1": (12.5, 4.5), "acr:10.0.0.2": (13.0, 6.0), "acr:10.0.0.3": (10.5, 3.0),
             "acr:10.0.0.4": (-6.5, 1.0), "acr:10.0.0.5": (30.0, -10.0)}
    requests.post(f"{MEC}/_mock/cells/cell01", json={"dl_gbr_prb_usage_cell": 35, "ul_gbr_prb_usage_cell": 10,
                                                     "dl_nongbr_prb_usage_cell": 27, "ul_nongbr_prb_usage_cell": 8})
    while not stop.is_set():
        for a, (x, y) in spots.items():
            lat, lon = FRAME.to_latlon(x, y)
            try:
                requests.post(f"{MEC}/_mock/users/{a}", json={"lat": lat, "lon": lon, "accuracy": 2}, timeout=1)
            except requests.RequestException:
                pass
        time.sleep(0.5)


async def run_agent():
    async with MCPHub(default_servers()) as hub:
        rep = await SafetyAgent(hub).shift_report()
        workflow_log = list(hub.log)                         # the report's own tool calls
        guard = await hub.call("in", "write_content", container="EdgeGuard/nearmiss", content="{}")
        return rep, {s: [t.name for t in ts] for s, ts in hub.tools.items()}, workflow_log, guard


def smoke_test_servers():
    """The MCP servers must at least build; report why not (CI annotation) instead of a bare 'connection closed'."""
    for mod, call in (("agent.onem2m_mcp", "m.build('in', 'http://127.0.0.1:8080', 'cse-in', 'SEdgeGuardAgent', ['EdgeGuardAgent'])"),
                      ("agent.mec_mcp", "m.build('http://127.0.0.1:8085', 'location/v3', 'rni/v2', 37.55, 127.07)")):
        r = subprocess.run([sys.executable, "-c", f"import {mod} as m; {call}"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            print(f"::error title=MCP server {mod}::" + " | ".join(r.stderr.strip().splitlines()[-6:])[:1500])


def main():
    smoke_test_servers()
    rng = random.Random(7)
    mock = ensure_mec_mock()
    stop = threading.Event()
    threading.Thread(target=people_feed, args=(stop,), daemon=True).start()
    time.sleep(1.0)
    mec, hc = seed(rng)

    rep1, tools, log1, guard = asyncio.run(run_agent())
    bad = [c for c in log1 if c.get("error")]
    if bad and any(c["tool"] == "connect" for c in bad):
        try:
            tail = open(os.path.join(ROOT, "results", "mcp_servers.log")).read().strip().splitlines()[-8:]
            print("::error title=MCP server stderr::" + " | ".join(tail)[:1500])
        except OSError:
            pass
    if any(c["tool"] == "connect" for c in bad) or rep1.get("errors"):     # diagnostics (CI annotations)
        print("::warning title=agent_demo run 1::" + json.dumps({"tools": {k: len(v) for k, v in tools.items()},
              "errors": rep1.get("errors"), "failed_calls": bad[:6]}, default=str)[:1500])
    # shift goes on: five more close passes at the blind corner; then zone B's MN-CSE fails
    for i in range(5):
        mec.create_cin("EdgeGuard/nearmiss", near_miss(rng, 12, 4, "forklift_01", "worker_01", occluded=True))
    subprocess.run(["bash", os.path.join(ROOT, "scripts", "acme.sh"), "stop", "mn-b"], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    rep2, _, log2, _ = asyncio.run(run_agent())
    subprocess.run(["bash", os.path.join(ROOT, "scripts", "acme.sh"), "start", "mn-b"], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    stop.set()

    ag = OneM2MClient(*IN, AGENT)
    stored = ag.latest(f"{AGENT_AE}/reports")
    state = ag.latest(f"{AGENT_AE}/state")
    top = rep1["hotspots"][0] if rep1["hotspots"] else {}
    speed = next((h for h in rep1["hotspots"] if h["advice"] == "speed"), {})
    routed = [c for c in log1 if c["tool"] == "retrieve" and "forklift_01" in json.dumps(c.get("args"))]
    checks = {
        "tools discovered on 4 MCP servers (IN, zone A, zone B, ETSI MEC)": len(tools) == 4 and all(tools.values()),
        "multi-step workflow: every step ran and validated": rep1["status"] == "complete" and all(rep1["validation"].values())
            and len(log1) >= 10,
        "routing: forklift_01 queried on zone B's server (found through its home record)":
            bool(routed) and routed[0]["server"] == "mn-b" and rep1["forklifts"]["forklift_01"]["speed_limit"] == 1.5,
        "blind corner found as the top hotspot (12, 4)": (top.get("x"), top.get("y"), top.get("advice")) == (12, 4, "blind_corner"),
        "fast-traffic hotspot names the forklift without a speed limit":
            speed.get("forklifts") == ["forklift_02"] and any("forklift_02 currently without a speed limit" in r
                                                               for r in rep1["recommendations"]),
        "MEC context: people near the blind corner (Location) and radio load (RNIS)":
            top.get("people_now", 0) >= 3 and top.get("radio_load_pct") == 62,
        "persistent state: run 2 read only the 5 new near misses": rep2["near_misses_new"] == 5 and state.get("runs") == 1,
        "error handling: zone B down -> partial report, error recorded, still saved":
            rep2["status"] == "partial" and rep2["forklifts"].get("forklift_01", {}).get("status") == "unreachable"
            and stored.get("status") == "partial",
        "guardrail: the agent cannot write outside its own AE": isinstance(guard, dict) and guard.get("error") == "forbidden",
    }
    out = {"run1": rep1, "run2": rep2, "tools": tools, "tool_calls_run1": log1, "checks": checks}
    json.dump(out, open(os.path.join(ROOT, "results", "agent.json"), "w"), indent=1, default=str)
    print("run 1:", rep1["status"], "-", len(log1), "tool calls;", "; ".join(rep1["recommendations"][:3]))
    print("run 2:", rep2["status"], "-", rep2["near_misses_new"], "new;", [e.get("step") for e in rep2["errors"]])
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    if mock:
        mock.terminate()
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=agent::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v], "tool_calls": len(log1)}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:                   # visible in CI annotations
        import traceback
        tb = traceback.format_exc().strip().splitlines()
        print("::error title=agent_demo::" + " | ".join(tb[-6:])[:1500])
        raise
