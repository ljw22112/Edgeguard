"""Forklift swarm coordination through oneM2M (edgeguard/swarm.py), on an ACME CSE.

    scripts/acme.sh start in
    python tools/swarm_demo.py

Four forklifts in zone A plan routes through two intersections (I1 blind corner, I2 dock crossing).
Each publishes its plan, reads the swarm's shared context with one group request and computes its own
start delay.  Checked: every member computes the same schedule, the schedule is conflict-free, and it
costs less time than reacting at the intersections (first come first served, brake and wait).  Then a
forklift leaves the zone (removed from the group) and a loaded one joins: the swarm re-plans.
Result: results/swarm.json
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.onem2m import OneM2MClient, OneM2MError                         # noqa: E402
from edgeguard.swarm import SwarmGroup, SwarmMember, conflicts, reactive_delays   # noqa: E402

CSE = ("http://127.0.0.1:8080", "cse-in")
MEC, MEC_AE = "SEdgeGuardSwarm", "EdgeGuardSwarm"
ROUTES = {    # (intersection, arrival time in s from now at the planned speed)
    "fk1": ([("I1", 6.0), ("I2", 14.0)], 0),
    "fk2": ([("I1", 7.5)], 0),
    "fk3": ([("I2", 13.0), ("I1", 20.0)], 0),
    "fk4": ([("I2", 15.0)], 0),
    "fk5": ([("I1", 6.5), ("I2", 12.0)], 1),     # joins later, loaded (priority)
}


def main():
    admin = OneM2MClient(*CSE, "CAdmin")
    for rn in [MEC_AE] + [f"sw_{f}" for f in ROUTES]:
        admin.delete(rn)
    mec = OneM2MClient(*CSE, MEC)
    mec.create_ae(MEC_AE)
    origins = {f: f"Csw{f}" for f in ROUTES}
    members = {f: SwarmMember(OneM2MClient(*CSE, o), f, readers=list(origins.values()) + [MEC]).join() for f, o in origins.items()}
    grp = SwarmGroup(mec, MEC_AE, "A").setup(acp_readers=list(origins.values()))

    def round_(fids):
        grp.set_members(fids)
        plans = [members[f].publish_plan(*ROUTES[f]) for f in fids]
        decisions = {f: members[f].decide(grp.path) for f in fids}
        scheds = [json.dumps(d["schedule"], sort_keys=True) for d in decisions.values()]
        delays = decisions[fids[0]]["schedule"]
        base = reactive_delays(plans)
        return {"members": fids, "delays": delays, "consistent": len(set(scheds)) == 1,
                "conflicts_without": len(conflicts(plans)), "conflicts_with": len(conflicts(plans, delays)),
                "total_delay_s": round(sum(delays.values()), 2), "reactive_total_delay_s": round(sum(base.values()), 2),
                "context_ms": [d["context_ms"] for d in decisions.values()],
                "everyone_sees_all": all(d["members"] == sorted(fids) for d in decisions.values())}

    r1 = round_(["fk1", "fk2", "fk3", "fk4"])
    r2 = round_(["fk1", "fk3", "fk4"])                    # fk2 leaves the zone
    r3 = round_(["fk1", "fk3", "fk4", "fk5"])             # fk5 (loaded) joins
    try:
        OneM2MClient(*CSE, "CIntruder").request("GET", f"{grp.path}/fopt/la")
        outsider = False
    except OneM2MError as e:
        outsider = e.status == 403
    advice = admin.request("GET", "sw_fk3/advice/la")["m2m:cin"]["con"]
    advice = json.loads(advice) if isinstance(advice, str) else advice
    ctx = sorted(ms for r in (r1, r2, r3) for ms in r["context_ms"])
    checks = {
        "shared context: every member read all members' plans with one group request": all(r["everyone_sees_all"] for r in (r1, r2, r3)),
        "all members computed the same schedule (no coordinator)": all(r["consistent"] for r in (r1, r2, r3)),
        "conflicts in the plans without coordination": r1["conflicts_without"] > 0,
        "swarm schedule is conflict-free": all(r["conflicts_with"] == 0 for r in (r1, r2, r3)),
        "swarm schedule costs less time than reacting at the intersections": all(
            r["total_delay_s"] < r["reactive_total_delay_s"] for r in (r1, r2, r3) if r["conflicts_without"]),
        "member left: the swarm re-planned without it": "fk2" not in r2["delays"] and r2["conflicts_with"] == 0,
        "loaded forklift joined and goes first (priority)": r3["delays"].get("fk5") == 0.0 and r3["conflicts_with"] == 0,
        "adopted advice is published in oneM2M": advice.get("delay_s") == r3["delays"]["fk3"],
        "a non-member cannot read the swarm context (ACP)": outsider,
    }
    report = {"rounds": [r1, r2, r3], "context_read_ms": {"median": ctx[len(ctx) // 2], "max": ctx[-1]}, "checks": checks}
    json.dump(report, open(os.path.join(ROOT, "results", "swarm.json"), "w"), indent=1)
    for r in (r1, r2, r3):
        print(f"  members {r['members']}: delays {r['delays']}; conflicts {r['conflicts_without']} -> {r['conflicts_with']}; "
              f"total delay {r['total_delay_s']} s vs reactive {r['reactive_total_delay_s']} s")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=swarm::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v],
         "delay_vs_reactive": [(r["total_delay_s"], r["reactive_total_delay_s"]) for r in (r1, r2, r3)],
         "context_ms": report["context_read_ms"]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
