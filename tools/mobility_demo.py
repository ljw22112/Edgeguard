"""Mobility through ETSI MEC and oneM2M: network-triggered CSE handover, zone events, signal strength.

    scripts/acme.sh start in mn-a mn-b
    python tools/mobility_demo.py

Two warehouse zones, each with a 5G small cell (POA) and an MN-CSE.  The MEC platform (mec_mock playing
scenarios/edgeguard-two-zones.yaml: forklift_01 drives A -> B -> A at 4 m/s) reports UE positions,
zone events (MEC 013) and per-UE radio measurements (MEC 012).  The event-driven MEC-IPE
(edgeguard/mobility.py) turns them into oneM2M resources, and oneM2M applications request MEC services
through it.  The forklift's handover between zone MN-CSEs is triggered by the NETWORK: the MEC zone
event "forklift_01 ENTERING zoneB", delivered as a oneM2M notification.  Results: results/mobility.json
(timeline for docs/img/mobility_map.html, tools/mobility_map.py).
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard import sdt                                                   # noqa: E402
from edgeguard.handover import HandoverClient, Zone, setup_home             # noqa: E402
from edgeguard.mobility import MecIpe, MecServiceClient, rn_of, rsrp_dbm    # noqa: E402
from edgeguard.onem2m import OneM2MClient, parse_notification              # noqa: E402
from mec_mock.scenario_player import ScenarioPlayer, _Frame                 # noqa: E402

SCENARIO = os.path.join(ROOT, "scenarios", "edgeguard-two-zones.yaml")
MOCK_PORT, RX_PORT, IPE_PORT = 8086, 9331, 9330
MEC = f"http://127.0.0.1:{MOCK_PORT}"
IN = ("http://127.0.0.1:8080", "cse-in", "id-in")
DEV, KIND, ORIGIN, APP = "forklift_01", "forklift", "SForklift01", "SEdgeGuard"
ZONES = [Zone("A", "http://127.0.0.1:8081", "cse-mn-a", "id-mn-a", (0.0, 0.0, 40.0, 30.0)),
         Zone("B", "http://127.0.0.1:8082", "cse-mn-b", "id-mn-b", (40.0, 0.0, 80.0, 30.0))]
MEC_ZONE = {"zoneA": "A", "zoneB": "B"}
DURATION = 29.0


class Rx:
    def __init__(self):
        self.kin, self.zone_dev, self.zone_app, self.radio, self.resp = [], [], [], [], []
        self.on_dev_zone = None
        self.svc = None
        rx = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                t = time.time()
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                self.send_response(200)
                self.send_header("X-M2M-RSC", "2000")
                self.end_headers()
                kind, p = parse_notification(body)
                if self.path == "/kin" and kind == "fcnt":
                    rx.kin.append((t, p.get("smpTe"), self.headers.get("X-M2M-Origin", "")))
                elif self.path == "/radio" and kind == "fcnt":
                    rx.radio.append((t, p))
                elif self.path == "/resp" and kind == "cin":
                    rx.resp.append((t, p))
                    rx.svc and rx.svc.on_response(p)
                elif self.path in ("/devzone", "/appzone") and kind == "cin" and isinstance(p, dict):
                    (rx.zone_dev if self.path == "/devzone" else rx.zone_app).append((t, p))
                    if self.path == "/devzone" and rx.on_dev_zone:
                        rx.on_dev_zone(p)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", RX_PORT), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


def gap_metrics(rx, sent, ev, period=0.1):
    t0, t1 = ev.t_start - 1.0, (ev.t_switch or ev.t_start) + 2.0
    arr = sorted(t for t, _, _ in rx if t0 <= t <= t1)
    gap = max((b - a for a, b in zip(arr, arr[1:])), default=0.0)
    got = {ts for _, ts, _ in rx}
    win = [s for s in sent if s[2] and t0 <= s[3] <= t1]
    return {"interruption_ms": round(max(0.0, gap - period) * 1000, 1),
            "samples_in_window": len(win), "samples_lost": sum(1 for s in win if s[0] not in got)}


def main():
    sc = yaml.safe_load(open(SCENARIO))
    fr = sc["edgeguard"]["frame"]
    frame = _Frame(fr["lon0"], fr["lat0"])
    env = dict(os.environ, MEC_MOCK_SCENARIO=SCENARIO, MEC_MOCK_GIS_PERIOD="0.25")
    mock = subprocess.Popen([sys.executable, "-m", "uvicorn", "mec_mock.server:app", "--port", str(MOCK_PORT),
                             "--log-level", "warning"], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                            stdout=open(os.path.join(ROOT, "results", "mec_mock_mobility.log"), "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if requests.get(f"{MEC}/_mock/scenario", timeout=0.5).ok:
                    break
            except requests.RequestException:
                time.sleep(0.1)
        return run(frame)
    finally:
        mock.terminate()


def run(frame):
    t0_mock = requests.get(f"{MEC}/_mock/scenario", timeout=2).json()["t0"]
    truth = ScenarioPlayer.load(SCENARIO, period=0.0, t0=t0_mock)       # the forklift's own (UWB) position

    def pos(t=None):
        u = truth.users(t)[DEV]
        return frame.xy(u["lon"], u["lat"])

    admin = OneM2MClient(IN[0], IN[1], "CAdmin")
    for rn in ("MEC-IPE", DEV):
        admin.delete(rn)
    for z in ZONES:
        OneM2MClient(z.base_url, z.cse_rn, "CAdmin").delete(DEV)

    rx = Rx()
    url = f"http://127.0.0.1:{RX_PORT}"
    ipe = MecIpe(OneM2MClient(IN[0], IN[1], "SMecIpe"), MEC, listen=("127.0.0.1", IPE_PORT),
                 readers=[APP, ORIGIN], log=lambda *a: None).setup()

    # --- the oneM2M application asks for MEC services through oneM2M only ----------------------------------
    app = OneM2MClient(IN[0], IN[1], APP)
    app.create_subscription("MEC-IPE/responses", "sub_app", [f"{url}/resp"])
    app.create_subscription("MEC-IPE/zoneEvents", "sub_app", [f"{url}/appzone"])
    svc = MecServiceClient(app)
    rx.svc = svc
    r_zone = svc.call("zone_subscribe", zones=["zoneA", "zoneB"])
    r_radio = svc.call("radio_subscribe", ues=[DEV])
    r_loc = svc.call("location", ue=DEV)

    # --- the forklift: home record, twin on zone A, handover triggered by the network -----------------------
    cfg = {"forklift": {"max_speed": 4.5}, "handover": {"in_cse_id": IN[2], "subscribers": [f"{url}/kin"]}}
    home = OneM2MClient(IN[0], IN[1], ORIGIN)
    setup_home(home, DEV, [APP])
    hc = HandoverClient(cfg, DEV, KIND, ORIGIN, ZONES, home=home, readers=[APP], trigger="network", log=lambda *a: None)
    hc.attach(*pos())
    acp_ri = OneM2MClient(ZONES[0].base_url, ZONES[0].cse_rn, APP).request("GET", f"{DEV}/acp_{DEV}")["m2m:acp"]["ri"]
    OneM2MClient(ZONES[0].base_url, ZONES[0].cse_rn, APP).create_subscription(
        sdt.kin_path(DEV, KIND), "sub_app", [f"{url}/kin"], acpi=[acp_ri])
    triggers = []

    def on_zone(ev):                                   # MEC zone event -> network-side handover trigger
        if ev.get("ue") == DEV and ev.get("event") == "ENTERING_AREA_EVENT" and ev.get("zone") in MEC_ZONE:
            started = hc.network_trigger(MEC_ZONE[ev["zone"]])
            triggers.append({"t": time.time(), "zone": ev["zone"], "started": started, "mec_ts": ev["mec_ts"]})
    rx.on_dev_zone = on_zone
    OneM2MClient(IN[0], IN[1], ORIGIN).create_subscription("MEC-IPE/zoneEvents", "sub_dev", [f"{url}/devzone"])
    for _ in range(30):                                # the radio flexContainer appears with the first report
        if DEV in ipe.ues:
            break
        time.sleep(0.1)
    app.create_subscription(f"MEC-IPE/{rn_of(DEV)}/radio", "sub_app", [f"{url}/radio"], net=(1,))

    # --- drive ---------------------------------------------------------------------------------------------
    sent, timeline = [], []
    t_start = time.time()
    while time.time() - t_start < DURATION:
        now = time.time()
        x, y = pos(now)
        ts = int(now * 1000)
        zone = hc.publish({"id": DEV, "kind": KIND, "x": round(x, 3), "y": round(y, 3), "speed": 4.0, "heading": 0.0,
                           "yaw_rate": 0.0, "ts": ts})
        sent.append((ts, zone, zone is not None, now))
        rad = rx.radio[-1][1] if rx.radio else {}
        net = next((e for _, e in reversed(rx.zone_app) if e.get("ue") == DEV and e.get("event") == "ENTERING_AREA_EVENT"), {})
        timeline.append({"t": round(now - t_start, 2), "x": round(x, 2), "y": round(y, 2), "serving_cse": hc.serving,
                         "mec_zone": net.get("zone"), "cell": rad.get("srvCl"), "rsrp_dbm": rsrp_dbm(rad.get("rsrp")),
                         "nb_cell": rad.get("nbCl"), "nb_rsrp_dbm": rsrp_dbm(rad.get("nbRp")), "pending": hc.pending is not None})
        time.sleep(max(0.0, t_start + (len(sent)) * 0.1 - time.time()))
    time.sleep(1.0)

    # --- unsubscribe through oneM2M as well -------------------------------------------------------------------
    ids = r_zone.get("result", {}).get("subscriptions", []) + r_radio.get("result", {}).get("subscriptions", [])
    r_un = svc.call("unsubscribe", subscriptions=ids)
    left = requests.get(f"{MEC}/_mock/subscriptions", timeout=2).json()
    mock_events = [e for e in requests.get(f"{MEC}/_mock/events", timeout=2).json() if e["address"] == DEV]

    # --- evaluation -------------------------------------------------------------------------------------------
    evs = [e for e in hc.events if not e.error]
    hos = [{"from": e.source, "to": e.target, "reason": e.reason, "t": round(e.t_start - t_start, 2),
            "prep_ms": round(e.prep_ms, 1), **gap_metrics(rx.kin, sent, e)} for e in evs]
    lat = sorted(ev["written"] * 1000 - ev["mec_ts"] for ev in ipe.event_log if ev["ue"] == DEV)
    trig_lat = [round((h_ev.t_start - tr["t"]) * 1000, 1) for h_ev in evs for tr in triggers
                if tr["started"] and abs(h_ev.t_start - tr["t"]) < 0.5]
    radios = [p for _, p in rx.radio]
    cells = [p.get("srvCl") for p in radios]
    hist = admin.request("GET", f"MEC-IPE/{rn_of(DEV)}/radio")["egs:rdLnk"]
    at_ho = []
    cell_of = {"A": "cellA", "B": "cellB"}
    for h_ev in evs:                                # first radio report on the new cell after the network moved the UE
        tgt, src = cell_of[h_ev.target], cell_of[h_ev.source]
        rep = next((p for t, p in rx.radio if t >= h_ev.t_start - 0.5 and p.get("srvCl") == tgt and p.get("nbCl") == src), None)
        at_ho.append({"t": round(h_ev.t_start - t_start, 2), "x": min(timeline, key=lambda r: abs(r["t"] - (h_ev.t_start - t_start)))["x"],
                      "cell": tgt, "rsrp_dbm": rsrp_dbm((rep or {}).get("rsrp")),
                      "nb_cell": src, "nb_rsrp_dbm": rsrp_dbm((rep or {}).get("nbRp"))})
    disc = admin.discover_label("egs:mec/ue", ty=28)
    checks = {
        "oneM2M application subscribed to MEC zone events through the IPE (2 MEC subscriptions)":
            r_zone.get("ok") and len(r_zone["result"]["subscriptions"]) == 2,
        "oneM2M application got the forklift's MEC location through the IPE":
            r_loc.get("ok") and (r_loc["result"].get("user") or {}).get("address") == DEV,
        "MEC zone events reached oneM2M (ENTERING zoneB, then zoneA again)":
            [e["zone"] for _, e in rx.zone_app if e.get("ue") == DEV and e["event"] == "ENTERING_AREA_EVENT"][:2] == ["zoneB", "zoneA"],
        "handover A -> B -> A triggered by the network (location trigger off)":
            [(h["from"], h["to"], h["reason"]) for h in hos] == [("A", "B", "network"), ("B", "A", "network")],
        "no sample lost in either handover": bool(hos) and all(h["samples_lost"] == 0 for h in hos),
        "service interruption < 300 ms in each handover": bool(hos) and all(h["interruption_ms"] < 300 for h in hos),
        "signal strength in oneM2M (egs:rdLnk): serving cell cellA -> cellB -> cellA":
            "cellB" in cells and cells[0] == "cellA" and cells[-1] == "cellA" and bool(hist.get("srvCl")),
        "at each handover the new cell is received stronger than the old one":
            bool(at_ho) and all(a["rsrp_dbm"] is not None and a["nb_rsrp_dbm"] is not None and a["rsrp_dbm"] >= a["nb_rsrp_dbm"]
                                for a in at_ho),
        "MEC data discoverable as SDT twins (lbl egs:mec/ue)": any(rn_of(DEV) in d for d in disc),
        "MEC subscriptions removed through oneM2M": r_un.get("ok") and not left,
    }
    report = {"scenario": "scenarios/edgeguard-two-zones.yaml", "handovers": hos, "radio_at_handover": at_ho,
              "requests": {"zone_subscribe_rtt_ms": r_zone.get("_rtt_ms"), "radio_subscribe_rtt_ms": r_radio.get("_rtt_ms"),
                           "location_rtt_ms": r_loc.get("_rtt_ms")},
              "zone_event_to_onem2m_ms": {"n": len(lat), "median": round(statistics.median(lat), 1) if lat else None},
              "zone_event_to_handover_start_ms": trig_lat, "network_events": mock_events, "triggers": triggers,
              "ipe": ipe.stats, "radio_reports": len(radios),
              "zones": {z.name: {"rect": z.rect, "cse": z.cse_id} for z in ZONES},
              "poas": {"poa-a": {"cell": "cellA", "xy": [20, 15]}, "poa-b": {"cell": "cellB", "xy": [60, 15]}},
              "workers": {n: [round(v, 1) for v in frame.xy(u["lon"], u["lat"])] for n, u in truth.users().items() if n != DEV},
              "timeline": timeline, "checks": checks}
    ipe.close()
    json.dump(report, open(os.path.join(ROOT, "results", "mobility.json"), "w"), indent=1)
    for h, a in zip(hos, at_ho):
        print(f"  {h['from']} -> {h['to']} ({h['reason']}) at x={a['x']} m: prepared {h['prep_ms']} ms, interruption "
              f"{h['interruption_ms']} ms, lost {h['samples_lost']}/{h['samples_in_window']}; "
              f"new {a['cell']} {a['rsrp_dbm']} dBm vs old {a['nb_cell']} {a['nb_rsrp_dbm']} dBm")
    print(f"  MEC zone event -> oneM2M: median {report['zone_event_to_onem2m_ms']['median']} ms; "
          f"requests via oneM2M: {report['requests']}")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=mobility::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks),
         "handovers": [(h["from"], h["to"], h["interruption_ms"], h["samples_lost"]) for h in hos],
         "event_ms": report["zone_event_to_onem2m_ms"]["median"]}))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("::error title=mobility_demo::" + " | ".join(traceback.format_exc().strip().splitlines()[-6:])[:1500])
        raise
