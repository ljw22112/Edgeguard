"""Which oneM2M features EdgeGuard relies on does a CSE support?  Plain HTTP, one request per check.

    python tools/cse_probe.py --cse http://127.0.0.1:8080 --rn cse-in   --name ACME
    python tools/cse_probe.py --cse http://127.0.0.1:3000 --rn TinyIoT  --name tinyIoT
    -> results/cse_probe_<name>.json, and a line per feature

Each check creates what it needs under a fresh AE and deletes the AE at the end.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG, NOTIFY_PORT = "CProbe", 9411
GOT: list[dict] = []


class _Notify(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            GOT.append(json.loads(body or b"{}"))
        except ValueError:
            pass
        self.send_response(200)
        self.send_header("X-M2M-RSC", "2000")
        self.end_headers()

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cse", default="http://127.0.0.1:8080")
    ap.add_argument("--rn", default="cse-in")
    ap.add_argument("--name", default="ACME")
    a = ap.parse_args()
    base = f"{a.cse}/{a.rn}"

    def req(method, path, origin=ORIG, ty=None, body=None, params=None):
        h = {"X-M2M-Origin": origin, "X-M2M-RI": uuid.uuid4().hex[:10], "X-M2M-RVI": "3", "Accept": "application/json"}
        if body is not None:
            h["Content-Type"] = "application/json" + (f";ty={ty}" if ty else "")
        r = requests.request(method, f"{base}/{path}".rstrip("/"), headers=h, params=params,
                             data=json.dumps(body) if body is not None else None, timeout=5)
        try:
            j = r.json()
        except ValueError:
            j = {}
        return r.status_code, j

    srv = ThreadingHTTPServer(("127.0.0.1", NOTIFY_PORT), _Notify)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    req("DELETE", "probe_ae", "CAdmin")
    res = {}

    def check(name, ok, detail=""):
        res[name] = {"ok": bool(ok), "detail": detail}
        print(f"{'yes ' if ok else 'no  '} {name}" + (f"  ({detail})" if detail else ""))

    st, _ = req("POST", "", ty=2, body={"m2m:ae": {"rn": "probe_ae", "api": "Nprobe", "rr": True, "srv": ["3"],
                                                   "poa": [f"http://127.0.0.1:{NOTIFY_PORT}"], "lbl": ["probe/edgeguard"]}})
    check("AE registration", st == 201, str(st))
    st, _ = req("POST", "probe_ae", ty=3, body={"m2m:cnt": {"rn": "kin", "mni": 5}})
    check("container with maxNrOfInstances", st == 201, str(st))
    st, _ = req("POST", "probe_ae/kin", ty=4, body={"m2m:cin": {"con": {"x": 1.0, "y": 2.0}}})
    check("contentInstance with a JSON object as content", st == 201, str(st))
    st2, _ = req("POST", "probe_ae/kin", ty=4, body={"m2m:cin": {"con": json.dumps({"x": 1.0, "y": 3.0})}})
    check("contentInstance with text content", st2 == 201, str(st2))
    st, j = req("GET", "probe_ae/kin/la")
    check("latest (la)", st == 200 and "m2m:cin" in j, str(st))
    st, j = req("GET", "", "CAdmin", params={"fu": 1, "lbl": "probe/edgeguard", "ty": 2})
    check("discovery by label", any(u.endswith("probe_ae") for u in j.get("m2m:uril", [])), str(st))
    GOT.clear()
    st, _ = req("POST", "probe_ae/kin", ty=23, body={"m2m:sub": {"rn": "sub", "nu": [f"{a.rn}/probe_ae"], "enc": {"net": [3]}}})
    req("POST", "probe_ae/kin", ty=4, body={"m2m:cin": {"con": "notify-me"}})
    time.sleep(1.0)
    check("subscription and notification to the AE's pointOfAccess", st == 201 and any("m2m:sgn" in g and not g["m2m:sgn"].get("vrq") for g in GOT), str(st))
    st, _ = req("POST", "probe_ae", ty=1, body={"m2m:acp": {"rn": "acp", "pv": {"acr": [{"acor": ["COther"], "acop": 2}]},
                                                             "pvs": {"acr": [{"acor": [ORIG], "acop": 63}]}}})
    check("ACP under an AE", st == 201, str(st))
    st, _ = req("POST", "probe_ae", ty=1, body={"m2m:acp": {"rn": "acp_chty", "pv": {"acr": [{"acor": ["COther"], "acop": 1, "acod": [{"chty": [23]}]}]},
                                                             "pvs": {"acr": [{"acor": [ORIG], "acop": 63}]}}})
    check("ACP with accessControlObjectDetails (chty)", st == 201, str(st))
    req("POST", "probe_ae", ty=3, body={"m2m:cnt": {"rn": "inbox"}})
    st, _ = req("POST", "probe_ae", ty=9, body={"m2m:grp": {"rn": "zone", "mt": 3, "mnm": 10, "mid": [f"{a.rn}/probe_ae/kin", f"{a.rn}/probe_ae/inbox"]}})
    fst, _ = req("POST", "probe_ae/zone/fopt", ty=4, body={"m2m:cin": {"con": "DANGER"}}) if st == 201 else (0, {})
    check("group and fanOutPoint (one request to every member)", st == 201 and fst in (200, 201), f"group {st}, fopt {fst}")
    st, _ = req("POST", "probe_ae", ty=28, body={"cod:bat": {"rn": "battery", "cnd": "org.onem2m.common.moduleclass.battery",
                                                             "lvl": 80}})
    check("flexContainer, standard SDT class cod:bat", st == 201, str(st))
    st, _ = req("POST", "probe_ae", ty=15, body={"m2m:pch": {"rn": "pch"}})
    check("pollingChannel (devices behind NAT)", st == 201, str(st))
    st, _ = req("POST", "probe_ae/kin", ty=24, body={"m2m:smd": {"rn": "smd", "dcrp": 5,
                                                                   "dsp": base64.b64encode(b"@prefix s: <https://saref.etsi.org/core/> . <urn:probe> a s:Device .").decode()}})
    check("semanticDescriptor", st == 201, str(st))
    req("DELETE", "probe_ae", "CAdmin")
    srv.shutdown()
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", f"cse_probe_{a.name}.json"), "w") as f:
        json.dump({"cse": a.name, "checks": res}, f, indent=1)
    print(f"{sum(v['ok'] for v in res.values())}/{len(res)} features on {a.name}")


if __name__ == "__main__":
    main()
