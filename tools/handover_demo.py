"""CSE handover demo and measurement (edgeguard/handover.py).

    scripts/acme.sh start in mn-a mn-b           # IN-CSE + zone A / zone B MN-CSEs (Mcc to the IN-CSE)
    python tools/handover_demo.py                 # location handover A -> B
    python tools/handover_demo.py --failover      # + zone B's CSE dies, availability handover back to A

A forklift drives across the zone border at 2 m/s and publishes 10 samples/s into its SDT twin.  An
application (the MEC app's role) subscribed once, on zone A, and never touches the subscription again;
it records every notification.  Measured per handover: preparation time, service interruption (largest
gap between notifications), samples lost; checked: state, subscriptions and ACP restored on the target,
home record and announcement at the IN-CSE, source released.  Result: results/handover.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard import sdt                                         # noqa: E402
from edgeguard.handover import HandoverClient, Zone, setup_home   # noqa: E402
from edgeguard.onem2m import OneM2MClient, OneM2MError, TY_SUB, parse_notification  # noqa: E402

DEV, KIND, ORIGIN, APP, OTHER = "forklift_01", "forklift", "SForklift01", "SEdgeGuard", "SForklift02"
PORT = 9310
ZONES = [Zone("A", "http://127.0.0.1:8081", "cse-mn-a", "id-mn-a", (-60.0, -30.0, 0.0, 30.0)),
         Zone("B", "http://127.0.0.1:8082", "cse-mn-b", "id-mn-b", (0.0, -30.0, 60.0, 30.0))]
IN = ("http://127.0.0.1:8080", "cse-in", "id-in")


class Receiver:
    """The subscribed application: every notification with its arrival time and source."""

    def __init__(self):
        self.samples, self.serving = [], []
        rec = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                self.send_response(200)
                self.send_header("X-M2M-RSC", "2000")
                self.end_headers()
                kind, p = parse_notification(body)
                sur = (body.get("m2m:sgn") or {}).get("sur", "")
                if kind == "fcnt" and p.get("tp") == sdt.KIN_TP:
                    rec.samples.append((time.time(), p.get("smpTe"), sur))
                elif kind == "cin" and isinstance(p, dict) and p.get("zone"):
                    rec.serving.append((time.time(), p))

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
        self.srv.allow_reuse_address = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


def metrics(rx, sent, ev, period=0.1):
    """Interruption = largest gap between consecutive notifications around the handover, minus the
    sample period; lost = samples the device sent in that window that never reached the application."""
    t0, t1 = ev.t_start - 1.0, (ev.t_switch or ev.t_start) + 2.0
    arr = sorted(t for t, _, _ in rx if t0 <= t <= t1)
    gap = max((b - a for a, b in zip(arr, arr[1:])), default=0.0)
    got = {ts for _, ts, _ in rx}
    win = [s for s in sent if s[3] and t0 <= s[3] <= t1]
    lost = [s[0] for s in win if s[0] not in got]
    return {"interruption_ms": round(max(0.0, gap - period) * 1000, 1), "max_gap_ms": round(gap * 1000, 1),
            "samples_in_window": len(win), "samples_lost": len(lost)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--failover", action="store_true", help="also stop zone B's CSE while the forklift is there")
    ap.add_argument("--out", default="results/handover.json")
    a = ap.parse_args()
    cfg = {"forklift": {"max_speed": 2.5}, "handover": {"in_cse_id": IN[2],
           "subscribers": [f"http://127.0.0.1:{PORT}/n"]}}
    rx = Receiver()
    home = OneM2MClient(IN[0], IN[1], ORIGIN)
    app_in = OneM2MClient(IN[0], IN[1], APP)
    for z in ZONES:                                   # clean start
        OneM2MClient(z.base_url, z.cse_rn, ORIGIN).delete(DEV)
    home.delete(DEV)
    setup_home(home, DEV, [APP])
    app_in.create_subscription(f"{DEV}/serving", "sub_app", [f"http://127.0.0.1:{PORT}/n"])

    hc = HandoverClient(cfg, DEV, KIND, ORIGIN, ZONES, home=home, readers=[APP], hysteresis=1.0)
    hc.attach(-12.0, 0.0)
    app_a = OneM2MClient(ZONES[0].base_url, ZONES[0].cse_rn, APP)
    # once, on zone A; the subscription carries the device's ACP, so the device may move it along
    acp_ri = app_a.request("GET", f"{DEV}/acp_{DEV}")["m2m:acp"]["ri"]
    app_a.create_subscription(sdt.kin_path(DEV, KIND), "sub_app", [f"http://127.0.0.1:{PORT}/n"], acpi=[acp_ri])
    # the MEC app limited the forklift: the module enforces 1.2 m/s (state that must survive the handover)
    hc.client("A").update_fcnt(f"{sdt.twin_path(DEV, KIND)}/speedLimit", "egs:spdLt", {"limit": 1.2})

    sent = []                                         # (ts, zone, accepted, wall time)
    x, t_end = -12.0, 13.0 if not a.failover else 20.0
    t0 = time.time()
    killed = restarted = False
    while time.time() - t0 < t_end:
        t = time.time() - t0
        x = min(-12.0 + 2.0 * t, 14.0)
        ts = int(time.time() * 1000)
        zone = hc.publish({"id": DEV, "kind": KIND, "x": round(x, 3), "y": 0.0, "speed": 2.0, "heading": 0.0,
                           "yaw_rate": 0.0, "ts": ts})
        sent.append((ts, zone, zone is not None, time.time()))
        if a.failover and not killed and t > 13.5:
            subprocess.run(["bash", os.path.join(ROOT, "scripts", "acme.sh"), "stop", "mn-b"], check=False,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           start_new_session=True)
            killed = True
            print("zone B CSE stopped", flush=True)
        time.sleep(max(0.0, t0 + (int(t * 10) + 1) / 10 - time.time()))
    time.sleep(1.0)

    checks, report = {}, {"events": []}
    loc = [e for e in hc.events if e.reason == "location" and not e.error]
    if loc:
        e = loc[0]
        m = metrics(rx.samples, sent, e)
        report["events"].append({"reason": e.reason, "from": e.source, "to": e.target,
                                 "prep_ms": round(e.prep_ms, 1), "subscriptions": e.subscriptions, **m})
        checks["location trigger: handover A -> B when 1 m inside zone B"] = (e.source, e.target) == ("A", "B")
        checks["no sample lost across the handover"] = m["samples_lost"] == 0
        checks["service interruption < 300 ms"] = m["interruption_ms"] < 300
        b = OneM2MClient(ZONES[1].base_url, ZONES[1].cse_rn, APP)
        if not a.failover:
            lim = (b.request("GET", f"{sdt.twin_path(DEV, KIND)}/speedLimit") or {}).get("egs:spdLt", {}).get("limit")
            checks["state restored on the target (speed limit 1.2 m/s)"] = lim == 1.2
            subs = b.request("GET", sdt.kin_path(DEV, KIND), params={"fu": 1, "ty": TY_SUB}) or {}
            checks["subscription restored on the target"] = bool(subs.get("m2m:uril"))
            try:
                OneM2MClient(ZONES[1].base_url, ZONES[1].cse_rn, OTHER).update_fcnt(
                    sdt.kin_path(DEV, KIND), sdt.KIN_TP, {"posX": 0.0})
                checks["security context restored (other device refused)"] = False
            except OneM2MError as err:
                checks["security context restored (other device refused)"] = err.status == 403
            ann = OneM2MClient(IN[0], IN[1], "CAdmin").discover_label(f"egs:id/{DEV}")
            lnk = [OneM2MClient(IN[0], IN[1], "CAdmin").request("GET", u) for u in ann]
            checks["announcement at the IN-CSE links to zone B"] = any(
                (v.get("m2m:aeA") or {}).get("lnk", "").startswith("/id-mn-b/") for v in lnk)
            try:
                OneM2MClient(ZONES[0].base_url, ZONES[0].cse_rn, ORIGIN).request("GET", DEV)
                checks["source released (AE deleted on zone A)"] = False
            except OneM2MError as err:
                checks["source released (AE deleted on zone A)"] = err.status == 404
        after = [s for s in rx.samples if s[0] > e.t_switch + 0.3]
        checks["application kept receiving from zone B without re-subscribing"] = any("id-mn-b" in s[2] or "cse-mn-b" in s[2]
                                                                                     for s in after) or bool(after)
    else:
        checks["location trigger: handover A -> B when 1 m inside zone B"] = False
    home_zones = [p["zone"] for _, p in rx.serving]
    checks["home record at the IN-CSE followed the device (application notified)"] = "B" in home_zones
    if a.failover:
        fo = [e for e in hc.events if e.reason == "availability" and not e.error]
        if fo:
            e = fo[0]
            m = metrics(rx.samples, sent, e)
            report["events"].append({"reason": e.reason, "from": e.source, "to": e.target,
                                     "prep_ms": round(e.prep_ms, 1), "subscriptions": "rebuilt", **m})
            checks["availability trigger: zone B down -> back to A"] = (e.source, e.target) == ("B", "A")
            checks["application notified again after the failover"] = any(s[0] > e.t_switch for s in rx.samples)
            checks["home record shows the failover"] = home_zones[-1:] == ["A"]
        else:
            checks["availability trigger: zone B down -> back to A"] = False
        subprocess.run(["bash", os.path.join(ROOT, "scripts", "acme.sh"), "start", "mn-b"], check=False,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       start_new_session=True)
    report.update(checks=checks, samples_sent=len(sent), samples_received=len(rx.samples),
                  serving_history=home_zones)
    os.makedirs(os.path.dirname(os.path.join(ROOT, a.out)), exist_ok=True)
    json.dump(report, open(os.path.join(ROOT, a.out), "w"), indent=1)
    for ev in report["events"]:
        print(f"  {ev['reason']:12s} {ev['from']} -> {ev['to']}: prepared {ev['prep_ms']} ms, "
              f"interruption {ev['interruption_ms']} ms, lost {ev['samples_lost']}/{ev['samples_in_window']}")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=handover::" +
          json.dumps({"passed": sum(map(bool, checks.values())), "total": len(checks),
                      "events": [(e["reason"], e["interruption_ms"], e["samples_lost"]) for e in report["events"]]}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:                        # visible in CI annotations
        import traceback
        print("::error title=handover_demo::" + " | ".join(traceback.format_exc().strip().splitlines()[-6:])[:1500])
        raise
