"""A oneM2M safety app in about 100 lines of plain HTTP (docs/tutorial-onem2m.md).

    scripts/acme.sh start in        # any oneM2M CSE with HTTP binding; ACME on :8080 by default
    python tools/tutorial_safety_app.py

No EdgeGuard code: only `requests`, so every oneM2M request is visible.  A worker tag registers and publishes
its position; a safety app finds the tag by label, subscribes to it, and when the worker walks into the
forklift aisle writes an alert into the tag's own inbox.  The tag's access control policy lets the app read
the position and create alerts, nothing else.
"""
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

CSE = os.environ.get("CSE", "http://127.0.0.1:8080")
CSE_RN = os.environ.get("CSE_RN", "cse-in")
TAG, APP = "CTutorialTag", "CTutorialApp"          # originators ("C..." = the CSE assigns nothing, we choose)
APP_PORT = 9399
AISLE_Y = (7.0, 13.0)                               # the forklift lane, metres


def m2m(method, path, origin, ty=None, body=None, params=None):
    """One oneM2M request over HTTP (TS-0009): originator, request id and release version in headers."""
    h = {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex[:12], "X-M2M-RVI": "3", "Accept": "application/json"}
    if body is not None:
        h["Content-Type"] = "application/json" + (f";ty={ty}" if ty else "")
    r = requests.request(method, f"{CSE}/{CSE_RN}/{path}".rstrip("/"), headers=h, params=params,
                         data=json.dumps(body) if body is not None else None, timeout=5)
    print(f"  {method:6} /{CSE_RN}/{path}  ({origin}) -> {r.status_code} rsc={r.headers.get('X-M2M-RSC')}")
    return r


alerts_seen = []


class AppEndpoint(BaseHTTPRequestHandler):
    """The safety app's notification target (its pointOfAccess)."""

    def do_POST(self):
        sgn = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["m2m:sgn"]
        self.send_response(200)
        self.send_header("X-M2M-RSC", "2000")
        self.end_headers()
        if sgn.get("vrq"):                                  # the CSE checks the target before it accepts the subscription
            return
        pos = sgn["nev"]["rep"]["m2m:cin"]["con"]
        if AISLE_Y[0] <= pos["y"] <= AISLE_Y[1]:            # the "risk engine" of this tutorial
            m2m("POST", "tutorial_tag/alerts", APP, 4, {"m2m:cin": {"con": {"cue": "WAIT", "reason": "in forklift aisle"}}})
            alerts_seen.append(pos)

    def log_message(self, *a):
        pass


def main():
    for ae in ("tutorial_tag", "tutorial_app"):           # clean up a previous run
        requests.delete(f"{CSE}/{CSE_RN}/{ae}", headers={"X-M2M-Origin": "CAdmin", "X-M2M-RI": "x", "X-M2M-RVI": "3"}, timeout=5)

    print("1. The tag registers (AE) with a label, then creates its containers")
    m2m("POST", "", TAG, 2, {"m2m:ae": {"rn": "tutorial_tag", "api": "Ntutorial.tag", "rr": False, "srv": ["3"],
                                        "lbl": ["tutorial/worker-tag", "zone/A"]}})
    m2m("POST", "tutorial_tag", TAG, 3, {"m2m:cnt": {"rn": "position", "mni": 50}})
    m2m("POST", "tutorial_tag", TAG, 3, {"m2m:cnt": {"rn": "alerts", "mni": 20}})

    print("2. The tag decides who may do what: the app may find the tag, read and subscribe to the position, and create alerts")
    acp = m2m("POST", "tutorial_tag", TAG, 1, {"m2m:acp": {"rn": "acp_tag",
              "pv": {"acr": [{"acor": [TAG], "acop": 63},
                             {"acor": [APP], "acop": 2 + 32 + 16 + 1, "acod": [{"chty": [23]}]}]},   # RETRIEVE, DISCOVERY, NOTIFY, CREATE subscriptions
              "pvs": {"acr": [{"acor": [TAG], "acop": 63}]}}}).json()["m2m:acp"]["ri"]
    alerts_acp = m2m("POST", "tutorial_tag", TAG, 1, {"m2m:acp": {"rn": "acp_alerts",
              "pv": {"acr": [{"acor": [TAG], "acop": 63}, {"acor": [APP], "acop": 1, "acod": [{"chty": [4]}]}]},   # CREATE contentInstances only
              "pvs": {"acr": [{"acor": [TAG], "acop": 63}]}}}).json()["m2m:acp"]["ri"]
    ae_acp = m2m("POST", "tutorial_tag", TAG, 1, {"m2m:acp": {"rn": "acp_ae",
              "pv": {"acr": [{"acor": [TAG], "acop": 63}, {"acor": [APP], "acop": 2 + 32}]},              # the app may find the tag
              "pvs": {"acr": [{"acor": [TAG], "acop": 63}]}}}).json()["m2m:acp"]["ri"]
    m2m("PUT", "tutorial_tag", TAG, body={"m2m:ae": {"acpi": [ae_acp]}})
    m2m("PUT", "tutorial_tag/position", TAG, body={"m2m:cnt": {"acpi": [acp]}})
    m2m("PUT", "tutorial_tag/alerts", TAG, body={"m2m:cnt": {"acpi": [alerts_acp]}})

    print("3. The app registers with a pointOfAccess and finds tags by label (discovery)")
    srv = ThreadingHTTPServer(("127.0.0.1", APP_PORT), AppEndpoint)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    m2m("POST", "", APP, 2, {"m2m:ae": {"rn": "tutorial_app", "api": "Ntutorial.app", "rr": True, "srv": ["3"],
                                        "poa": [f"http://127.0.0.1:{APP_PORT}"]}})
    found = m2m("GET", "", APP, params={"fu": 1, "lbl": "tutorial/worker-tag", "ty": 2}).json().get("m2m:uril", [])
    print(f"     found: {found}")

    print("4. The app subscribes to each tag's position; notifications go to its pointOfAccess")
    for ae in found:
        m2m("POST", f"{ae.split('/')[-1]}/position", APP, 23,
            {"m2m:sub": {"rn": "sub_app", "nu": [f"{CSE_RN}/tutorial_app"], "enc": {"net": [3]}}})

    print("5. The tag walks toward the aisle, publishing its position")
    for y in (20.0, 16.0, 12.5, 10.0):
        m2m("POST", "tutorial_tag/position", TAG, 4, {"m2m:cin": {"con": {"x": 31.0, "y": y}}})
        time.sleep(0.4)
    time.sleep(1.0)

    print("6. The tag reads its inbox; a stranger is refused")
    la = (m2m("GET", "tutorial_tag/alerts/la", TAG).json().get("m2m:cin") or {}).get("con") or {}
    print(f"     latest alert: {la}")
    stranger = m2m("POST", "tutorial_tag/alerts", "CStranger", 4, {"m2m:cin": {"con": {"cue": "GO"}}}).status_code
    app_read_alerts = m2m("GET", "tutorial_tag/alerts/la", APP).status_code

    checks = {
        "tag found by label discovery": any(u.endswith("tutorial_tag") for u in found),
        "alerts written by the app for both positions inside the aisle": [p["y"] for p in alerts_seen] == [12.5, 10.0],
        "the tag received WAIT in its own inbox": la.get("cue") == "WAIT",
        "a stranger cannot write the tag's alerts (403)": stranger == 403,
        "the app may create alerts but not read them (403)": app_read_alerts == 403,
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    srv.shutdown()
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
