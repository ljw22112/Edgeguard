"""Run the event-driven MEC-IPE against a real MEC platform (ETSI MEC Sandbox or a self-hosted AdvantEDGE).

    scripts/acme.sh start in
    python tools/mec_events_check.py --mec http://<advantedge>/<sandbox>/mep1 --callback http://<this host>:9330 \
        --zones zone01 zone02 --ues 10.100.0.1 --seconds 120

Subscribes through oneM2M (MEC-IPE/requests) to MEC 013 zone events for the given zones and to MEC 012
MeasRepUe reports for the given UEs, runs for --seconds while the scenario moves the UEs, then
unsubscribes.  The platform must reach --callback (same LAN, or a tunnel).  Result:
results/mec_events_live.json with every zone event and radio report that reached oneM2M.
CI runs the same code against mec_mock (tools/mobility_demo.py); this is the check for a real platform.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.mobility import MecIpe, MecServiceClient   # noqa: E402
from edgeguard.onem2m import OneM2MClient                 # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mec", required=True, help="MEC platform base URL (before location/v3)")
    ap.add_argument("--callback", required=True, help="URL the MEC platform reaches this host at, e.g. http://192.168.0.20:9330")
    ap.add_argument("--zones", nargs="+", required=True)
    ap.add_argument("--ues", nargs="*", default=[])
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--cse", default="http://127.0.0.1:8080/cse-in")
    a = ap.parse_args()
    base, rn = a.cse.rstrip("/").rsplit("/", 1)
    OneM2MClient(base, rn, "CAdmin").delete("MEC-IPE")
    ipe = MecIpe(OneM2MClient(base, rn, "SMecIpe"), a.mec, listen=("0.0.0.0", int(a.callback.rsplit(":", 1)[1].split("/")[0])),
                 readers=["SEdgeGuardCheck"], callback=a.callback, log=print).setup()
    app = OneM2MClient(base, rn, "SEdgeGuardCheck")
    svc = MecServiceClient(app)
    # the app reads responses by polling here (no notification server needed for a one-off check)
    def call(op, **kw):
        n0 = len(app.discover("MEC-IPE/responses", ty=4))
        rqi = f"chk{time.time_ns() % 10**9}"
        app.create_cin("MEC-IPE/requests", {"rqi": rqi, "op": op, **kw})
        for _ in range(50):
            for u in app.discover("MEC-IPE/responses", ty=4)[n0:]:
                con = app.request("GET", u)["m2m:cin"]["con"]
                con = json.loads(con) if isinstance(con, str) else con
                if con.get("rqi") == rqi:
                    return con
            time.sleep(0.1)
        return {"ok": False, "error": "no response"}
    del svc
    r_zone = call("zone_subscribe", zones=a.zones)
    r_radio = call("radio_subscribe", ues=a.ues) if a.ues else {"ok": None}
    print("zone subscriptions:", r_zone, "\nradio subscription:", r_radio)
    t_end = time.time() + a.seconds
    while time.time() < t_end:
        time.sleep(5)
        print(f"  {int(t_end - time.time())} s left: {ipe.stats}")
    ids = (r_zone.get("result") or {}).get("subscriptions", []) + ((r_radio or {}).get("result") or {}).get("subscriptions", [])
    r_un = call("unsubscribe", subscriptions=ids)
    report = {"mec": a.mec, "zones": a.zones, "ues": a.ues, "subscribe": [r_zone, r_radio], "unsubscribe": r_un,
              "ipe": ipe.stats, "events": ipe.event_log}
    json.dump(report, open(os.path.join(ROOT, "results", "mec_events_live.json"), "w"), indent=1, default=str)
    ipe.close()
    ok = bool(r_zone.get("ok")) and ipe.stats["zone_events"] > 0
    print(("::notice" if ok else "::warning") + " title=mec_events_check::" + json.dumps(ipe.stats))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
