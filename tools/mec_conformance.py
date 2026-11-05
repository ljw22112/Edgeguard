"""Check EdgeGuard's ETSI MEC traffic against the official ETSI OpenAPI definitions.

    python tools/mec_conformance.py                       # -> results/mec_conformance.json, exit 1 on a violation

Runs the MEC mock with the two-zone scenario, drives EdgeGuard's own MEC clients (the MEC-IPE's MEC 013 / 012
subscriptions and location query, Mp1 = MEC 011, AMS = MEC 021) and records every exchange:

* requests EdgeGuard sends and the mock's responses, validated with openapi-core against the ETSI definition
  of that operation (path, parameters, request body, status, response body);
* notifications the mock sends to EdgeGuard's callbacks, validated against the ETSI notification schema.

The definitions are the ETSI Forge OpenAPI files in third_party/etsi-mec/ (BSD-3-Clause, ETSI). The base path
of each API is taken from what EdgeGuard and the ETSI MEC Sandbox use; a different version segment in the
definition's `servers` entry is reported as a note, not a failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.mec_platform import AmsClient, Mp1Client  # noqa: E402
from edgeguard.mobility import MecIpe  # noqa: E402

SPEC_DIR = os.path.join(ROOT, "third_party", "etsi-mec")
MOCK_PORT, CB_PORT = 18185, 18186
MEC = f"http://127.0.0.1:{MOCK_PORT}"
CB = f"http://127.0.0.1:{CB_PORT}"
SCENARIO = os.path.join(ROOT, "scenarios", "edgeguard-two-zones.yaml")

# base path used by EdgeGuard / the ETSI MEC Sandbox -> (ETSI definition file, API name)
APIS = {
    "/location/v3": ("LocationAPI.yaml", "MEC 013 Location"),
    "/rni/v2": ("RniAPI.yaml", "MEC 012 RNIS"),
    "/mec_service_mgmt/v1": ("MecServiceMgmtApi.yaml", "MEC 011 Service management"),
    "/mec_app_support/v2": ("MecAppSupportApi.yaml", "MEC 011 Application support"),
    "/amsi/v1": ("MEC021_AppMobilityService.yaml", "MEC 021 AMS"),
}
NOTIFICATIONS = {   # notificationType -> (definition, schema)
    "ZoneLocationEventNotification": ("LocationAPI.yaml", "ZoneLocationEventNotification"),
    "UserLocationEventNotification": ("LocationAPI.yaml", "UserLocationEventNotification"),
    "UserAreaNotification": ("LocationAPI.yaml", "UserAreaNotification"),
    "UserDistanceNotification": ("LocationAPI.yaml", "UserDistanceNotification"),
    "MeasRepUeNotification": ("RniAPI.yaml", "MeasRepUeNotification"),
    "SerAvailabilityNotification": ("MecServiceMgmtApi.yaml", "ServiceAvailabilityNotification"),
    "MobilityProcedureNotification": ("MEC021_AppMobilityService.yaml", "MobilityProcedureNotification"),
}

EXCHANGES: list[tuple[requests.PreparedRequest, requests.Response]] = []
NOTES: list[dict] = []
_orig = requests.Session.request


def _recording(self, method, url, *a, **kw):
    r = _orig(self, method, url, *a, **kw)
    if url.startswith(MEC) and "/_mock/" not in url:
        EXCHANGES.append((r.request, r))
    return r


class _Callbacks(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            NOTES.append({"path": self.path, "body": json.loads(body or b"{}")})
        except ValueError:
            NOTES.append({"path": self.path, "body": None})
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


SPEC_FIXES: list[str] = []


def _drop_ref_siblings(node):
    """The 3.1 files keep `type: object` next to `$ref` (left from the 3.0 conversion, where siblings of $ref were
    ignored); in 3.1 both apply and a string field could never validate. Keep the 3.0 meaning."""
    n = 0
    if isinstance(node, dict):
        if "$ref" in node and "type" in node:
            node.pop("type")
            n += 1
        for v in node.values():
            n += _drop_ref_siblings(v)
    elif isinstance(node, list):
        for v in node:
            n += _drop_ref_siblings(v)
    return n


def _spec(name):
    """An ETSI definition, with the defects of the published files fixed (each one listed in the report)."""
    with open(os.path.join(SPEC_DIR, name)) as f:
        d = yaml.safe_load(f)
    n = _drop_ref_siblings(d)
    if n:
        SPEC_FIXES.append(f"{name}: {n} `type` keys next to `$ref` dropped (3.0 meaning of $ref)")
    sch = d.get("components", {}).get("schemas", {})
    if name == "MEC021_AppMobilityService.yaml" and sch.get("AssociateId", {}).get("type") == "string":
        with open(os.path.join(SPEC_DIR, "RniAPI.yaml")) as f:
            sch["AssociateId"] = yaml.safe_load(f)["components"]["schemas"]["AssociateId"]
        SPEC_FIXES.append(f"{name}: AssociateId is a string placeholder 'as defined in MEC 012'; MEC 012 AssociateId used")
    if name == "MecAppSupportApi.yaml":
        ops = d["paths"].get("/applications/{appInstanceId}/confirm_ready", {}).get("post", {})
        if ops and "204" not in ops.get("responses", {}):
            ops["responses"]["204"] = {"description": "No Content"}
            SPEC_FIXES.append(f"{name}: confirm_ready defines no success response; 204 No Content added")
    if name == "MecServiceMgmtApi.yaml":
        ct = sch.get("ServiceReferences", {}).get("properties", {}).get("changeType", {})
        if ct.get("enum") == ["SEE_DESCRIPTION"]:
            ct["enum"] = ["ADDED", "REMOVED", "STATE_CHANGED", "ATTRIBUTES_CHANGED"]
            SPEC_FIXES.append(f"{name}: changeType enum is the placeholder SEE_DESCRIPTION; the four values of its description used")
    return d


def drive():
    """EdgeGuard's own clients, against the mock."""
    stub = types.SimpleNamespace(mec=MEC, cb=f"{CB}", loc_api="location/v3", rnis_api="rni/v2", mec_subs={},
                                 stats={"requests": 0, "errors": 0}, root="MEC-IPE", log=lambda *a: None,
                                 c=types.SimpleNamespace(create_cin=lambda *a, **k: None))
    stub._subscribe = MecIpe._subscribe.__get__(stub)
    stub._unsubscribe = MecIpe._unsubscribe.__get__(stub)
    stub._write_location = lambda *a, **k: None
    ipe = MecIpe.handle_request.__get__(stub)
    ues = list(requests.get(f"{MEC}/_mock/scenario", timeout=2).json()["ues"])
    ipe({"op": "zone_subscribe", "rqi": "1", "zones": ["zoneA", "zoneB"]})
    ipe({"op": "radio_subscribe", "rqi": "2", "ues": ues})
    ipe({"op": "area_subscribe", "rqi": "3", "name": "dock", "lat": 37.4979898, "lon": 127.0280, "radius": 20,
         "addresses": ues})
    if len(ues) >= 2:
        ipe({"op": "distance_subscribe", "rqi": "4", "name": "pair", "addresses": ues[:2], "distance": 30})
    ipe({"op": "location", "rqi": "5", "ue": ues[0]})

    mp1a, mp1b = Mp1Client(MEC, "edgeguard-a"), Mp1Client(MEC, "edgeguard-b")
    mp1a.confirm_ready()
    mp1a.subscribe_availability(f"{CB}/ser", names=["edgeguard-safety"])
    mp1b.register_service("edgeguard-safety", "http://mep-b:9090", onem2m={"cse": "http://mep-b:8082/cse-mn-b"})
    mp1a.discover("edgeguard-safety")

    ams = AmsClient(MEC, "edgeguard-a", "mep-a")
    ams.register(ues, comm=("mep-a", 9400))
    ams.subscribe(f"{CB}/ams")
    time.sleep(14.0)                                  # the scenario moves the UEs: zone, area, distance, AMS events
    if ues:
        ams.context_transferred(ues[0])
    time.sleep(1.0)
    for sid in list(stub.mec_subs):
        stub._unsubscribe(sid)
    mp1b.deregister_service("edgeguard-safety")


def validate():
    from openapi_core import OpenAPI
    from openapi_core.contrib.requests import RequestsOpenAPIRequest, RequestsOpenAPIResponse
    from openapi_schema_validator import OAS31Validator

    apis, report = {}, {"exchanges": [], "notifications": [], "notes": []}
    for base, (fname, title) in APIS.items():
        d = _spec(fname)
        declared = (d.get("servers") or [{}])[0].get("url", "")
        if not declared.endswith(base):
            report["notes"].append(f"{title}: EdgeGuard uses {base}; the definition ({d['info']['version']}) declares {declared}")
        d["servers"] = [{"url": MEC + base}]
        apis[base] = (OpenAPI.from_dict(d), title, d["info"]["version"])
    for req, rsp in EXCHANGES:
        path = req.url[len(MEC):].split("?")[0]
        base = next((b for b in APIS if path.startswith(b + "/")), None)
        row = {"method": req.method, "path": path, "status": rsp.status_code}
        if base is None:
            row["errors"] = ["no ETSI definition for this base path"]
        else:
            api, title, ver = apis[base]
            row["api"] = f"{title} {ver}"
            errs = []
            for kind, fn, arg in (("request", api.validate_request, (RequestsOpenAPIRequest(req),)),
                                  ("response", api.validate_response, (RequestsOpenAPIRequest(req), RequestsOpenAPIResponse(rsp)))):
                try:
                    fn(*arg)
                except Exception as e:                      # noqa: BLE001 - every validation error is a finding
                    detail = "; ".join(str(x).split("\n")[0][:200] for x in (getattr(e, "__cause__", None) and getattr(e.__cause__, "schema_errors", None) or [])) \
                        or str(getattr(e, "__cause__", None) or e).split("\n")[0][:300]
                    errs.append(f"{kind}: {type(e).__name__}: {detail}")
            row["errors"] = errs
        report["exchanges"].append(row)
    specs = {f: _spec(f) for f in {v[0] for v in NOTIFICATIONS.values()}}
    for n in NOTES:
        body = n["body"] or {}
        inner = next(iter(body.values())) if len(body) == 1 and isinstance(next(iter(body.values())), dict) else body
        nt = inner.get("notificationType")
        row = {"path": n["path"], "notificationType": nt}
        if nt not in NOTIFICATIONS:
            row["errors"] = [f"unknown notificationType {nt!r}"]
        else:
            fname, schema = NOTIFICATIONS[nt]
            d = specs[fname]
            v = OAS31Validator({"$ref": f"#/components/schemas/{schema}", "components": d["components"]})
            row["schema"] = f"{d['info']['title']} {d['info']['version']}: {schema}"
            row["wrapped"] = inner is not body
            row["errors"] = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:200]}" for e in v.iter_errors(inner)]
        report["notifications"].append(row)
    return report


def main():
    env = dict(os.environ, MEC_MOCK_SCENARIO=SCENARIO, MEC_MOCK_GIS_PERIOD="0.25", MEC_MOCK_HOSTS="zoneA=mep-a,zoneB=mep-b")
    mock = subprocess.Popen([sys.executable, "-m", "uvicorn", "mec_mock.server:app", "--port", str(MOCK_PORT),
                             "--log-level", "warning"], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    srv = ThreadingHTTPServer(("127.0.0.1", CB_PORT), _Callbacks)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    requests.Session.request = _recording
    try:
        for _ in range(100):
            try:
                if _orig(requests.Session(), "GET", f"{MEC}/_mock/scenario", timeout=0.5).ok:
                    break
            except requests.RequestException:
                time.sleep(0.1)
        drive()
    finally:
        requests.Session.request = _orig
        mock.terminate()
        srv.shutdown()
    report = validate()
    ex_bad = [r for r in report["exchanges"] if r["errors"]]
    no_bad = [r for r in report["notifications"] if r["errors"]]
    report["spec_fixes"] = sorted(set(SPEC_FIXES))
    report["summary"] = {"exchanges": len(report["exchanges"]), "exchanges_conformant": len(report["exchanges"]) - len(ex_bad),
                         "notifications": len(report["notifications"]), "notifications_conformant": len(report["notifications"]) - len(no_bad),
                         "notification_types": sorted({r["notificationType"] for r in report["notifications"] if r["notificationType"]})}
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "mec_conformance.json"), "w") as f:
        json.dump(report, f, indent=1)
    for r in report["exchanges"]:
        print(("OK   " if not r["errors"] else "FAIL ") + f"{r['method']:6} {r['path']}  {r['status']}" + "".join(f"\n       {e}" for e in r["errors"]))
    for r in report["notifications"]:
        print(("OK   " if not r["errors"] else "FAIL ") + f"notify {r['notificationType']} -> {r['path']}" + "".join(f"\n       {e}" for e in r["errors"]))
    for n in report["notes"]:
        print("NOTE " + n)
    for n in report["spec_fixes"]:
        print("SPEC " + n)
    s = report["summary"]
    print(f"{s['exchanges_conformant']}/{s['exchanges']} exchanges and {s['notifications_conformant']}/{s['notifications']} notifications conform")
    return 0 if not ex_bad and not no_bad else 1


if __name__ == "__main__":
    sys.exit(main())
