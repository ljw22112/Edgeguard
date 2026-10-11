"""Zone broadcast through oneM2M <group> fan-out to tags behind NAT (<pollingChannel>), on an ACME CSE.

    scripts/acme.sh start in
    python tools/zone_demo.py

Four worker tags register with rr=false (no inbound connection, as a tag on a NAT'd Wi-Fi/LTE link) and
long-poll their pollingChannel.  The MEC app keeps one <group> per zone whose members are the tags'
`alerts` containers, moves tags between groups as they move, and sends every zone message with ONE
request to <group>/fopt.  Result: results/zones.json
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.onem2m import OneM2MClient, OneM2MError   # noqa: E402
from edgeguard.zones import PollingReceiver, ZoneGroups, setup_tag_inbox   # noqa: E402

CSE = ("http://127.0.0.1:8080", "cse-in")
MEC, MEC_AE = "SEdgeGuardZones", "EdgeGuardZones"
ZONES = {"A": (0, 0, 20, 20), "B": (20, 0, 40, 20)}
TAGS = ["zt1", "zt2", "zt3", "zt4"]
RUN = format(int(time.time() * 10) % 36 ** 5, "x")


def main():
    admin = OneM2MClient(*CSE, "CAdmin")
    for rn in TAGS + [MEC_AE, "tagp1", "tagp2", "EGtest"]:       # leftovers of earlier runs
        admin.delete(rn)

    mec = OneM2MClient(*CSE, MEC)
    mec.create_ae(MEC_AE)
    got, lock = [], threading.Lock()
    recv, clients = {}, {}
    for t in TAGS:
        # a fresh AE-ID per run: the CSE keys polling requests by originator, and a long poll left open by
        # a previous run (process gone, CSE still waiting) would otherwise swallow the first notifications
        dc = OneM2MClient(*CSE, f"C{t}r{RUN}", timeout=15)
        dc.create_ae(t)                                        # no poa: rr=false
        setup_tag_inbox(dc, t, writer=MEC)
        clients[t] = dc

        def on_alert(con, t_rx, t=t):
            with lock:
                got.append((t, con, t_rx))
        recv[t] = PollingReceiver(dc, t, on_alert).start()
    time.sleep(0.5)

    zg = ZoneGroups(mec, MEC_AE, ZONES)
    zg.setup()
    for t in TAGS:
        zg.register_tag(t)

    def send(zone, mid, wait=2.0, **extra):
        t0 = time.time()
        n = zg.broadcast(zone, {"id": mid, "zone": zone, "t": t0, **extra})
        end = time.time() + wait
        while time.time() < end:
            with lock:
                rx = [(t, tr) for t, c, tr in got if isinstance(c, dict) and c.get("id") == mid]
            if len(rx) >= n:
                break
            time.sleep(0.01)
        time.sleep(0.15)                                      # catch anything delivered to the wrong tag
        with lock:
            rx = [(t, tr) for t, c, tr in got if isinstance(c, dict) and c.get("id") == mid]
        return n, {t: round((tr - t0) * 1000, 1) for t, tr in rx}

    # 1. three tags in zone A, one in zone B
    pos = {"zt1": (5, 5), "zt2": (15, 8), "zt3": (30, 10), "zt4": (10, 15)}
    zg.update(pos)
    n1, rx1 = send("A", 1, wait=5, kind="forklift_entering", forklift="forklift_01")
    # 2. zt2 walks into zone B: membership follows
    pos["zt2"] = (24, 8)
    changed = zg.update(pos)
    n2, rx2 = send("B", 2, kind="blind_corner")
    grp = {z: mec.request("GET", f"{MEC_AE}/zone_{z}")["m2m:grp"] for z in ZONES}
    ri = {t: clients[t].request("GET", f"{t}/alerts")["m2m:cnt"]["ri"] for t in TAGS}
    def members(z):          # the CSE may store members as resource IDs or as structured paths
        return {t for t in TAGS for m in grp[z]["mid"] if m.split("/")[-1] == ri[t] or m.endswith(f"{t}/alerts")}
    # 3. latency over 30 zone-A broadcasts (2 recipients each)
    lat = []
    for i in range(30):
        _, rx = send("A", 100 + i, wait=1.5, kind="caution")
        lat += list(rx.values())
    lat.sort()
    # 4. access control
    intruder = OneM2MClient(*CSE, "CIntruder")
    def refused(fn):
        try:
            fn()
            return False
        except OneM2MError as e:
            return e.status in (403,)
    acl = {
        "another originator cannot write a tag's alerts": refused(lambda: intruder.create_cin("zt1/alerts", {"x": 1})),
        "the MEC app cannot subscribe to a tag's alerts (contentInstances only)":
            refused(lambda: mec.create_subscription("zt1/alerts", "spy", [MEC])),
        "the MEC app cannot read a tag's polling channel": refused(lambda: mec.request("GET", "zt1/pch/pcu")),
    }
    rr = {t: clients[t].request("GET", t)["m2m:ae"].get("rr") for t in TAGS}
    for r in recv.values():
        r.stop.set()

    p50 = statistics.median(lat) if lat else None
    p95 = lat[int(0.95 * (len(lat) - 1))] if lat else None
    checks = {
        "tags are not reachable from outside (rr=false), alerts arrive by polling": all(v is False for v in rr.values()),
        "one request to zone A reached exactly its 3 tags": n1 == 3 and sorted(rx1) == ["zt1", "zt2", "zt4"],
        "membership follows movement: zt2 moved from group A to group B":
            sorted(changed) == ["A", "B"] and members("B") == {"zt2", "zt3"} and members("A") == {"zt1", "zt4"},
        "after the move, zone B message reached zt2 and zt3 only": n2 == 2 and sorted(rx2) == ["zt2", "zt3"],
        "all 60 latency-run deliveries arrived": len(lat) == 60,
        "median fan-out + polling delivery under 50 ms": p50 is not None and p50 < 50,
        **{f"ACL: {k}": v for k, v in acl.items()},
    }
    report = {"zones": ZONES, "first": {"accepted": n1, "delivered_ms": rx1}, "after_move": {"accepted": n2, "delivered_ms": rx2},
              "groups": {z: sorted(members(z)) for z in ZONES}, "latency_ms": {"n": len(lat), "p50": p50, "p95": p95,
              "max": lat[-1] if lat else None}, "requests_per_zone_message": 1, "acl": acl, "checks": checks}
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(report, open(os.path.join(ROOT, "results", "zones.json"), "w"), indent=1)
    print(f"zone broadcast: 1 request -> {n1} tags; delivery p50 {p50} ms, p95 {p95} ms (n={len(lat)})")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=zones::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "p50_ms": p50, "p95_ms": p95}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
