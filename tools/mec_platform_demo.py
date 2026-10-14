"""EdgeGuard as a MEC application on the MEC platform APIs: MEC 011 (Mp1), MEC 021 (AMS), MEC 013 geofences.

    scripts/acme.sh start in mn-a mn-b
    python tools/mec_platform_demo.py

Two MEC hosts (mep-a for zone A, mep-b for zone B), one EdgeGuard app instance on each.

* Mp1: each instance confirms READY and registers the "edgeguard-safety" service; its transport info carries
  the oneM2M CSE and AE, so a MEC app that only speaks Mp1 finds the oneM2M resources.  The MEC-IPE is pointed
  at the Location service it discovers over Mp1.  A deregistration reaches subscribers as an availability
  notification.
* AMS: both instances register forklift_01 for mobility with context transfer.  When the forklift crosses into
  zone B, AMS tells the zone A instance INTERHOST_MOVEOUT_TRIGGERED with the target instance.  The source
  instance (1) sends the forklift's safety context to the target's commInterface, (2) moves the forklift's
  oneM2M twin to the zone B MN-CSE (handover trigger = AMS), (3) reports USER_CONTEXT_TRANSFER_COMPLETED, and
  AMS confirms INTERHOST_MOVEOUT_COMPLETED.  The same happens back B -> A.
* MEC 013 area and distance subscriptions, requested by a oneM2M application through the MEC-IPE: a circular
  geofence and a worker-forklift proximity watch; events land in <MEC-IPE>/geoEvents and are checked against
  the scenario's ground truth.

Results: results/mec_platform.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.handover import HandoverClient, Zone, setup_home             # noqa: E402
from edgeguard.mec_platform import AmsClient, Mp1Client                      # noqa: E402
from edgeguard.mobility import MecIpe, MecServiceClient                      # noqa: E402
from edgeguard.onem2m import OneM2MClient, parse_notification               # noqa: E402
from mec_mock.scenario_player import ScenarioPlayer, _Frame                  # noqa: E402

SCENARIO = os.path.join(ROOT, "scenarios", "edgeguard-two-zones.yaml")
MOCK_PORT, CB_PORT, IPE_PORT = 8087, 9341, 9340
MEC = f"http://127.0.0.1:{MOCK_PORT}"
CB = f"http://127.0.0.1:{CB_PORT}"
IN = ("http://127.0.0.1:8080", "cse-in", "id-in")
DEV, WORKER, KIND, ORIGIN, APP = "forklift_01", "worker_01", "forklift", "SForklift01", "SEdgeGuardP"
ZONES = [Zone("A", "http://127.0.0.1:8081", "cse-mn-a", "id-mn-a", (0.0, 0.0, 40.0, 30.0)),
         Zone("B", "http://127.0.0.1:8082", "cse-mn-b", "id-mn-b", (40.0, 0.0, 80.0, 30.0))]
INSTANCES = {"A": ("edgeguard-a", "mep-a"), "B": ("edgeguard-b", "mep-b")}
ZONE_OF_INSTANCE = {v[0]: k for k, v in INSTANCES.items()}
AREA = {"x": 60.0, "y": 10.0, "r": 6.0}
NEAR_M = 5.0
END_T = 30.0          # scenario time: the forklift is back past worker_01 in zone A


class Callbacks:
    """One HTTP server for both instances' MEC callbacks and the oneM2M notifications of the app."""

    def __init__(self):
        self.log: list[tuple[float, str, dict]] = []
        self.handlers = {}
        cb = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                t = time.time()
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                self.send_response(204 if not self.path.startswith("/m2m") else 200)
                if self.path.startswith("/m2m"):
                    self.send_header("X-M2M-RSC", "2000")
                self.end_headers()
                cb.log.append((t, self.path, body))
                h = cb.handlers.get(self.path)
                if h:
                    threading.Thread(target=h, args=(body,), daemon=True).start()

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", CB_PORT), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def of(self, path):
        return [(t, b) for t, p, b in self.log if p == path]


def main():
    env = dict(os.environ, MEC_MOCK_SCENARIO=SCENARIO, MEC_MOCK_GIS_PERIOD="0.25", MEC_MOCK_HOSTS="zoneA=mep-a,zoneB=mep-b")
    mock = subprocess.Popen([sys.executable, "-m", "uvicorn", "mec_mock.server:app", "--port", str(MOCK_PORT),
                             "--log-level", "warning"], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                            stdout=open(os.path.join(ROOT, "results", "mec_mock_platform.log"), "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if requests.get(f"{MEC}/_mock/scenario", timeout=0.5).ok:
                    break
            except requests.RequestException:
                time.sleep(0.1)
        return run()
    finally:
        mock.terminate()


def run():
    sc = yaml.safe_load(open(SCENARIO))
    frame = _Frame(sc["edgeguard"]["frame"]["lon0"], sc["edgeguard"]["frame"]["lat0"])
    t0_mock = requests.get(f"{MEC}/_mock/scenario", timeout=2).json()["t0"]
    truth = ScenarioPlayer.load(SCENARIO, period=0.0, t0=t0_mock)

    def xy(name, t=None):
        u = truth.users(t)[name]
        return frame.xy(u["lon"], u["lat"])

    admin = OneM2MClient(IN[0], IN[1], "CAdmin")
    for rn in ("MEC-IPE", DEV):
        admin.delete(rn)
    for z in ZONES:
        OneM2MClient(z.base_url, z.cse_rn, "CAdmin").delete(DEV)
    cbs = Callbacks()

    # --- Mp1: READY, own service with a oneM2M pointer, platform services ---------------------------------------
    mp1 = {z: Mp1Client(MEC, INSTANCES[z][0]) for z in INSTANCES}
    for z, m in mp1.items():
        m.confirm_ready()
    mp1["A"].subscribe_availability(f"{CB}/a/ser", names=["edgeguard-safety"])
    for z, m in mp1.items():
        zc = next(c for c in ZONES if c.name == z)
        m.register_service("edgeguard-safety", f"http://127.0.0.1:{CB_PORT}/{z.lower()}/api",
                           onem2m={"cseBase": f"{zc.base_url}/{zc.cse_rn}", "cseId": zc.cse_id, "ae": APP})
    found = mp1["A"].discover("edgeguard-safety")
    loc_ep = mp1["A"].endpoint("LocationService")
    ams_ep = mp1["A"].endpoint("AppMobilityService")

    # --- MEC-IPE on the discovered Location endpoint; geofences requested through oneM2M ------------------------
    ipe = MecIpe(OneM2MClient(IN[0], IN[1], "SMecIpe"), MEC, listen=("127.0.0.1", IPE_PORT), readers=[APP, ORIGIN],
                 location_api=(loc_ep or "/location/v3").lstrip("/"), log=lambda *a: None).setup()
    app = OneM2MClient(IN[0], IN[1], APP)
    svc = MecServiceClient(app)
    cbs.handlers["/m2m/resp"] = lambda b: svc.on_response(parse_notification(b)[1])
    app.create_subscription("MEC-IPE/responses", "sub_app", [f"{CB}/m2m/resp"])
    app.create_subscription("MEC-IPE/geoEvents", "sub_app", [f"{CB}/m2m/geo"])
    lon, lat = frame.lonlat(AREA["x"], AREA["y"])
    r_area = svc.call("area_subscribe", name="dock-b", addresses=[DEV], lat=lat, lon=lon, radius=AREA["r"],
                      events=["ENTERING_AREA_EVENT", "LEAVING_AREA_EVENT"])
    r_dist = svc.call("distance_subscribe", name="near-w1", addresses=[WORKER, DEV], distance=NEAR_M)

    # --- the forklift's oneM2M twin, handover trigger authority = AMS ------------------------------------------
    cfg = {"forklift": {"max_speed": 4.5}, "handover": {"in_cse_id": IN[2], "subscribers": []}}
    home = OneM2MClient(IN[0], IN[1], ORIGIN)
    setup_home(home, DEV, [APP])
    hc = HandoverClient(cfg, DEV, KIND, ORIGIN, ZONES, home=home, readers=[APP], trigger="network", log=lambda *a: None)
    hc.attach(*xy(DEV))
    state = {"last": None}

    # --- AMS: both instances serve forklift_01 -------------------------------------------------------------------
    ams = {z: AmsClient(MEC, INSTANCES[z][0], INSTANCES[z][1]) for z in INSTANCES}
    moves, ctx_rx = [], {}
    for z, a in ams.items():
        a.register([DEV], comm=("127.0.0.1", CB_PORT))
        a.subscribe(f"{CB}/{z.lower()}/ams")

    def on_ctx(z):
        def h(body):
            ctx_rx.setdefault(z, []).append(body)
        return h

    def on_ams(z):
        def h(body):
            ue = (body.get("associateId") or [{}])[0].get("value")
            st = body.get("mobilityStatus")
            rec = {"t": time.time(), "instance": INSTANCES[z][0], "ue": ue, "status": st,
                   "target": (body.get("targetAppInfo") or {}).get("appInstanceId")}
            moves.append(rec)
            if st != "INTERHOST_MOVEOUT_TRIGGERED" or ue != DEV or not rec["target"]:
                return
            tz = ZONE_OF_INSTANCE[rec["target"]]
            ip = ((body["targetAppInfo"].get("commInterface") or {}).get("ipAddresses") or [{}])[0]
            ctx = {"ue": DEV, "from": INSTANCES[z][0], "twin": f"{DEV}@{hc.serving}", "last": state["last"],
                   "risk": {"level": "SAFE", "alerts_open": 0}}
            t_a = time.time()
            requests.post(f"http://{ip.get('host')}:{ip.get('port')}/{tz.lower()}/ctx", json=ctx, timeout=2)
            rec["context_ms"] = round((time.time() - t_a) * 1000, 1)
            rec["handover_started"] = hc.network_trigger(tz, reason="ams")
            ams[z].context_transferred(DEV)
        return h
    for z in INSTANCES:
        cbs.handlers[f"/{z.lower()}/ams"] = on_ams(z)
        cbs.handlers[f"/{z.lower()}/ctx"] = on_ctx(z)

    # --- drive -----------------------------------------------------------------------------------------------
    n, t_start = 0, time.time()
    while time.time() - t0_mock < END_T:
        now = time.time()
        x, y = xy(DEV, now)
        s = {"id": DEV, "kind": KIND, "x": round(x, 3), "y": round(y, 3), "speed": 4.0, "heading": 0.0,
             "yaw_rate": 0.0, "ts": int(now * 1000)}
        hc.publish(s)
        state["last"] = s
        n += 1
        time.sleep(max(0.0, t_start + n * 0.1 - time.time()))
    time.sleep(1.0)

    # --- teardown: deregister zone B's service (availability notification), remove MEC subscriptions -------------
    mp1["B"].deregister_service("edgeguard-safety")
    time.sleep(0.5)
    ids = r_area.get("result", {}).get("subscriptions", []) + r_dist.get("result", {}).get("subscriptions", [])
    r_un = svc.call("unsubscribe", subscriptions=ids)
    plat = requests.get(f"{MEC}/_mock/platform", timeout=2).json()

    # --- evaluation -----------------------------------------------------------------------------------------
    geo = [(t, parse_notification(b)[1]) for t, b in cbs.of("/m2m/geo")]
    geo = [(t, e) for t, e in geo if isinstance(e, dict)]
    area_ev = [(t, e) for t, e in geo if e.get("kind") == "area"]
    dist_ev = [(t, e) for t, e in geo if e.get("kind") == "distance"]

    def dist_to_area(t):
        x, y = xy(DEV, t)
        return ((x - AREA["x"]) ** 2 + (y - AREA["y"]) ** 2) ** 0.5

    def ue_gap(t):
        (x1, y1), (x2, y2) = xy(DEV, t), xy(WORKER, t)
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
    area_rows = [{"event": e["event"], "t": round(e["mec_ts"] / 1000 - t0_mock, 2),
                  "dist_to_centre_m": round(dist_to_area(e["mec_ts"] / 1000), 2),
                  "mec_to_onem2m_ms": round(t * 1000 - e["mec_ts"], 1)} for t, e in area_ev]
    dist_rows = [{"event": e["event"], "ues": e["ues"], "t": round(e["mec_ts"] / 1000 - t0_mock, 2),
                  "gap_m": round(ue_gap(e["mec_ts"] / 1000), 2), "mec_to_onem2m_ms": round(t * 1000 - e["mec_ts"], 1)}
                 for t, e in dist_ev]
    trig = [m for m in moves if m["status"] == "INTERHOST_MOVEOUT_TRIGGERED" and m["ue"] == DEV]
    done = [m for m in moves if m["status"] == "INTERHOST_MOVEOUT_COMPLETED" and m["ue"] == DEV]
    hos = [(e.source, e.target, e.reason) for e in hc.events if not e.error]
    avail = [r for _, b in cbs.of("/a/ser") for r in b.get("serviceReferences", [])]
    o2m = [((s.get("transportInfo") or {}).get("implSpecificInfo") or {}).get("oneM2M") or {} for s in found]
    checks = {
        "Mp1: both instances READY, 'edgeguard-safety' discoverable on both hosts with its oneM2M CSE and AE":
            set(plat["ready"]) >= {"edgeguard-a", "edgeguard-b"} and len(found) == 2
            and {o.get("cseId") for o in o2m} == {"id-mn-a", "id-mn-b"} and all(o.get("ae") == APP for o in o2m),
        "Mp1: platform Location and AMS services discovered; the MEC-IPE runs on the discovered endpoint":
            loc_ep == "/location/v3" and ams_ep == "/amsi/v1" and ipe.loc_api == "location/v3",
        "Mp1: service availability notifications (ADDED x2, REMOVED on deregistration)":
            [r["changeType"] for r in avail].count("ADDED") == 2 and avail[-1:] and avail[-1]["changeType"] == "REMOVED",
        "AMS: move-out triggered A->B then B->A, each to the other host's instance":
            [(m["instance"], m["target"]) for m in trig] == [("edgeguard-a", "edgeguard-b"), ("edgeguard-b", "edgeguard-a")],
        "AMS: the forklift's safety context reached the target instance's commInterface each time":
            len(ctx_rx.get("B", [])) == 1 and len(ctx_rx.get("A", [])) == 1 and ctx_rx["B"][0].get("last") is not None,
        "AMS as handover trigger: oneM2M twin moved A->B->A (reason ams)":
            hos == [("A", "B", "ams"), ("B", "A", "ams")],
        "AMS: context transfer reported, INTERHOST_MOVEOUT_COMPLETED confirmed to each source":
            [m["instance"] for m in done] == ["edgeguard-a", "edgeguard-b"],
        "MEC 013 area (via oneM2M): ENTERING inside / LEAVING outside the geofence, within one GIS update (2 m)":
            [r["event"] for r in area_rows][:2] == ["ENTERING_AREA_EVENT", "LEAVING_AREA_EVENT"]
            and all((r["dist_to_centre_m"] <= AREA["r"]) == (r["event"] == "ENTERING_AREA_EVENT")
                    and abs(r["dist_to_centre_m"] - AREA["r"]) <= 2.0 for r in area_rows),
        f"MEC 013 distance (via oneM2M): worker_01 and forklift_01 within {NEAR_M:g} m, true gap <= {NEAR_M + 1:g} m":
            bool(dist_rows) and all(r["event"] == "ALL_WITHIN_DISTANCE" and r["gap_m"] <= NEAR_M + 1 for r in dist_rows),
        "all MEC 013 subscriptions removed through oneM2M":
            r_un.get("ok") and not plat["subscriptions"]["geo"],
    }
    report = {"scenario": "scenarios/edgeguard-two-zones.yaml", "instances": INSTANCES,
              "mp1": {"found": [{k: s[k] for k in ("serName", "serInstanceId", "transportInfo")} for s in found],
                      "location_endpoint": loc_ep, "ams_endpoint": ams_ep, "availability": avail},
              "ams": {"moves": [{**m, "t": round(m["t"] - t0_mock, 2)} for m in moves],
                      "context_received": ctx_rx, "handovers": hos},
              "geofence": {"area": AREA, "events": area_rows}, "distance": {"limit_m": NEAR_M, "events": dist_rows},
              "platform_log": plat["log"], "checks": checks}
    ipe.close()
    json.dump(report, open(os.path.join(ROOT, "results", "mec_platform.json"), "w"), indent=1, default=str)
    for m in trig:
        print(f"  AMS {m['instance']} -> {m['target']} at t={m['t'] - t0_mock:.2f}s: context {m.get('context_ms')} ms, "
              f"handover started {m.get('handover_started')}")
    for r in area_rows + dist_rows:
        print(f"  {r}")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=mec_platform::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v],
         "ams": [(m["instance"], m["target"]) for m in trig], "handovers": hos,
         "area": [(r["event"], r["dist_to_centre_m"]) for r in area_rows], "distance": [r["gap_m"] for r in dist_rows]}))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("::error title=mec_platform_demo::" + " | ".join(traceback.format_exc().strip().splitlines()[-6:])[:1500])
        raise
