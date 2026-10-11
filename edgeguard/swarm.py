"""Forklift swarm coordination through oneM2M (TR-0077 swarm computing).

Forklifts working the same zone form a swarm.  Membership is a oneM2M <group> (managed by the MEC app as
forklifts enter and leave the zone); each member publishes its plan - the intersections on its route with
arrival times, its priority (loaded / empty) - into its own `plan` container.  The shared context is read
with ONE request (<group>/fopt/la: the CSE returns every member's latest plan), and every member computes
the same conflict-free schedule locally from it, so the swarm needs no central coordinator and keeps
working if the MEC app is busy or away: the rule is deterministic, all members reach the same answer.

  sw_<forklift>        AE   (the member)
    plan               CNT  latest plan: {"id", "prio", "route": [[node, eta_s], ...], "ts"}
    advice             CNT  the delay it adopted (others and the dashboard can read it)
  <MEC AE>/swarm_<zone>  GRP  members = the plan containers of the forklifts in the zone
"""
from __future__ import annotations

import time

from .onem2m import ALL_OPS, CREATE, NOTIFY, RETRIEVE, DISCOVERY, OneM2MClient, OneM2MError, decode_con

TY_GRP = 9
HEADWAY_S = 4.0           # two forklifts are not scheduled through the same intersection within 4 s


def schedule(plans: list[dict], headway=HEADWAY_S):
    """Deterministic conflict-free schedule: higher priority first (loaded before empty), then the one that
    arrives first at its first intersection, then id.  Each forklift gets one start delay that keeps it
    `headway` seconds away from every earlier-scheduled forklift at every shared intersection.
    Returns {id: delay_s}."""
    order = sorted(plans, key=lambda p: (-int(p.get("prio", 0)), min((e for _, e in p["route"]), default=0.0), p["id"]))
    booked: dict[str, list[float]] = {}
    out = {}
    for p in order:
        d = 0.0
        for _ in range(200):
            shift = 0.0
            for node, eta in p["route"]:
                for t in booked.get(node, []):
                    if abs(eta + d - t) < headway - 1e-9:
                        shift = max(shift, t + headway - (eta + d))
            if shift <= 0:
                break
            d += shift
        out[p["id"]] = round(d, 3)
        for node, eta in p["route"]:
            booked.setdefault(node, []).append(eta + d)
    return out


def conflicts(plans: list[dict], delays: dict | None = None, headway=HEADWAY_S):
    """Pairs of forklifts at the same intersection within the headway."""
    delays = delays or {}
    out = []
    for i, a in enumerate(plans):
        for b in plans[i + 1:]:
            for na, ea in a["route"]:
                for nb, eb in b["route"]:
                    if na == nb and abs(ea + delays.get(a["id"], 0) - eb - delays.get(b["id"], 0)) < headway - 1e-9:
                        out.append((a["id"], b["id"], na))
    return out


def reactive_delays(plans: list[dict], headway=HEADWAY_S, stop_penalty=3.0):
    """Baseline without coordination: first come, first served at each intersection, the later forklift sees
    the other one late, brakes to a stop and waits; stopping and restarting costs `stop_penalty` seconds."""
    events = sorted(((eta, p["id"], node) for p in plans for node, eta in p["route"]))
    delay, last = {p["id"]: 0.0 for p in plans}, {}
    for eta, fid, node in events:
        t = eta + delay[fid]
        if node in last and t - last[node] < headway:
            delay[fid] += (last[node] + headway - t) + stop_penalty
            t = eta + delay[fid]
        last[node] = t
    return delay


class SwarmMember:
    def __init__(self, c: OneM2MClient, fid, readers=()):
        self.c, self.id, self.ae = c, fid, f"sw_{fid}"
        self.readers = list(readers)

    def join(self):
        c = self.c
        c.create_ae(self.ae, api="Nedgeguard.forklift", lbl=["egs:swarm/member", f"egs:id/{self.id}"])
        c.create_container(self.ae, "plan", mni=5)
        c.create_container(self.ae, "advice", mni=5)
        acp = c.create_acp(self.ae, f"acp_{self.ae}", [([c.origin], ALL_OPS), (self.readers, RETRIEVE | DISCOVERY | NOTIFY)],
                           [c.origin])
        for cnt in ("plan", "advice"):
            c.set_acpi(f"{self.ae}/{cnt}", f"{self.ae}/acp_{self.ae}", acp.get("ri"))
        return self

    def publish_plan(self, route, prio=0):
        plan = {"id": self.id, "prio": prio, "route": [[n, round(t, 2)] for n, t in route], "ts": int(time.time() * 1000)}
        self.c.create_cin(f"{self.ae}/plan", plan)
        return plan

    def context(self, group_path):
        """Every member's latest plan with one request to the group's fan-out point."""
        res = self.c.request("GET", f"{group_path}/fopt/la") or {}
        plans = []
        for r in (res.get("m2m:agr") or {}).get("m2m:rsp") or []:
            cin = (r.get("pc") or {}).get("m2m:cin")
            if int(r.get("rsc", 0)) == 2000 and cin:
                con = decode_con(cin.get("con"))
                if isinstance(con, dict) and con.get("route") is not None:
                    plans.append(con)
        return plans

    def decide(self, group_path):
        t0 = time.time()
        plans = self.context(group_path)
        ms = (time.time() - t0) * 1000
        sched = schedule(plans)
        mine = sched.get(self.id, 0.0)
        self.c.create_cin(f"{self.ae}/advice", {"id": self.id, "delay_s": mine, "members": sorted(p["id"] for p in plans),
                                                "ts": int(time.time() * 1000)})
        return {"delay": mine, "schedule": sched, "members": sorted(p["id"] for p in plans), "context_ms": round(ms, 1)}


class SwarmGroup:
    """MEC app side: one <group> per zone whose members are the plan containers of the forklifts in it."""

    def __init__(self, c: OneM2MClient, ae, zone, members_readers=()):
        self.c, self.ae, self.zone = c, ae, zone
        self.rn = f"swarm_{zone}"
        self.path = f"{ae}/{self.rn}"
        self.members: list[str] = []

    def setup(self, acp_readers=()):
        self.c.request("POST", self.ae, TY_GRP, {"m2m:grp": {"rn": self.rn, "mt": 3, "mid": [], "mnm": 50, "csy": 1}},
                       ok_conflict=True)
        if acp_readers:     # members may read the group (and fan out through it)
            acp = self.c.create_acp(self.ae, f"acp_{self.rn}", [([self.c.origin], ALL_OPS),
                                                                (list(acp_readers), RETRIEVE | CREATE)], [self.c.origin])
            self.c.request("PUT", self.path, None, {"m2m:grp": {"acpi": [acp["ri"]]}})
        return self

    def set_members(self, fids):
        self.members = sorted(fids)
        self.c.request("PUT", self.path, None, {"m2m:grp": {"mid": [f"{self.c.cse_rn}/sw_{f}/plan" for f in self.members]}})
