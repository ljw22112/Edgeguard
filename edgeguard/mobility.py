"""Event-driven, bidirectional MEC-IPE: ETSI MEC Location (013) and RNIS (012) <-> oneM2M.

The polling IPE (tools/mec_ipe.py) copies UE positions into the CSE.  This one also

* subscribes to MEC zone / user location events and RNIS measurement reports, and writes them into
  oneM2M as they happen (no polling): zone events as contentInstances, the per-UE radio link and
  location as SDT flexContainers (egs:mecUe with egs:ueLoc and egs:rdLnk, config/onem2m/edgeguard.fcp);
* accepts MEC service requests FROM oneM2M applications: an application creates a contentInstance in
  <MEC-IPE>/requests ({"rqi", "op": zone_subscribe | radio_subscribe | location | unsubscribe, ...}),
  the IPE calls the MEC API and answers in <MEC-IPE>/responses with the same rqi.  oneM2M applications
  thus use MEC services without speaking the MEC APIs or holding MEC credentials.

  MEC-IPE                       AE
    requests                    CNT   readers: create contentInstances only
    responses                   CNT   readers: read / subscribe
    zoneEvents                  CNT   one contentInstance per ENTERING / LEAVING event
    ue_<addr>                   egs:mecUe      lbl egs:mec/ue, egs:id/<addr>
      location                  egs:ueLoc      latest MEC 013 fix (history: flexContainerInstances)
      radio                     egs:rdLnk      serving / neighbour cell, RSRP, RSRQ (MEC 012)
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from .onem2m import ALL_OPS, CREATE, DISCOVERY, NOTIFY, RETRIEVE, OneM2MClient, OneM2MError, parse_notification

UE_TP, LOC_TP, RAD_TP = "egs:mecUe", "egs:ueLoc", "egs:rdLnk"
CND = "org.edgeguard.safety.{}"


def rn_of(address):
    return "ue_" + "".join(ch if ch.isalnum() else "_" for ch in str(address))


def rsrp_dbm(index):
    """3GPP reporting index -> dBm (lower edge of the 1 dB bin)."""
    return None if index is None else index - 141


class MecIpe:
    def __init__(self, cse: OneM2MClient, mec_url: str, listen=("127.0.0.1", 9330), root="MEC-IPE",
                 readers=(), location_api="location/v3", rnis_api="rni/v2", log=print, callback=None):
        """callback: the address the MEC platform reaches this IPE at (default http://<listen>), e.g. the
        host's LAN address when the platform is a self-hosted AdvantEDGE."""
        self.c, self.mec, self.root, self.readers = cse, mec_url.rstrip("/"), root, list(readers)
        self.loc_api, self.rnis_api, self.log = location_api, rnis_api, log
        self.listen = listen
        self.cb = (callback or f"http://{listen[0]}:{listen[1]}").rstrip("/")
        self.mec_subs: dict[str, str] = {}          # MEC subscription id -> its resource URL
        self.ues: set = set()
        self.stats = {"zone_events": 0, "radio_reports": 0, "requests": 0, "errors": 0, "location_updates": 0}
        self.event_log: list[dict] = []             # (for measurements) MEC timestamp vs written-to-oneM2M time
        self.srv = None

    # --- setup -----------------------------------------------------------------------------------------
    def setup(self):
        c, r = self.c, self.root
        if self.srv is None:
            self._serve()                 # before subscribing: the CSE verifies the notification URL
        c.create_ae(r, api="Nmec-ipe", poa=[f"{self.cb}/onem2m"], lbl=["egs:mec/ipe"])
        for cnt in ("requests", "responses", "zoneEvents"):
            c.with_retry(c.create_container, r, cnt, 200)
        own = [c.origin]
        rd = c.create_acp(r, "acp_ipe_read", [(own, ALL_OPS), (self.readers, RETRIEVE | DISCOVERY | NOTIFY | CREATE, (23,))], own)
        rq = c.create_acp(r, "acp_ipe_req", [(own, ALL_OPS), (self.readers, CREATE | RETRIEVE, (4,))], own)
        for cnt, acp, ri in (("responses", "acp_ipe_read", rd.get("ri")), ("zoneEvents", "acp_ipe_read", rd.get("ri")),
                             ("requests", "acp_ipe_req", rq.get("ri"))):
            c.set_acpi(f"{r}/{cnt}", f"{r}/{acp}", ri)
        self.acp_read = (f"{r}/acp_ipe_read", rd.get("ri"))
        c.create_subscription(f"{r}/requests", "sub_ipe", [f"{self.cb}/onem2m"])
        return self

    def _serve(self):
        ipe = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    body = {}
                t_rx = time.time()
                self.send_response(204 if self.path.startswith("/mec") else 200)
                if not self.path.startswith("/mec"):
                    self.send_header("X-M2M-RSC", "2000")
                self.end_headers()
                try:
                    if self.path.startswith("/mec/zone") or self.path.startswith("/mec/user"):
                        ipe.on_location_event(body, t_rx)
                    elif self.path.startswith("/mec/rnis"):
                        ipe.on_meas_rep(body, t_rx)
                    elif self.path.startswith("/onem2m"):
                        kind, con = parse_notification(body)
                        if kind == "cin" and isinstance(con, dict):
                            threading.Thread(target=ipe.handle_request, args=(con,), daemon=True).start()
                except Exception as e:
                    ipe.stats["errors"] += 1
                    ipe.log(f"MEC-IPE: {self.path}: {e}")

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(self.listen, H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        for sid in list(self.mec_subs):
            self._unsubscribe(sid)
        if self.srv:
            self.srv.shutdown()

    # --- oneM2M -> MEC: service requests ------------------------------------------------------------------
    def handle_request(self, con):
        self.stats["requests"] += 1
        op, rqi = con.get("op"), con.get("rqi")
        try:
            if op == "zone_subscribe":
                ids = []
                for z in con.get("zones") or []:
                    body = {"zoneLocationEventSubscription": {
                        "subscriptionType": "ZoneLocationEventSubscription",
                        "callbackReference": {"notifyURL": f"{self.cb}/mec/zone"}, "zoneId": z,
                        "locationEventCriteria": con.get("events") or ["ENTERING_AREA_EVENT", "LEAVING_AREA_EVENT"],
                        **({"addressList": con["addresses"]} if con.get("addresses") else {})}}
                    ids.append(self._subscribe(f"{self.loc_api}/subscriptions/zones", body))
                result = {"subscriptions": ids}
            elif op == "radio_subscribe":
                body = {"subscriptionType": "MeasRepUeSubscription", "callbackReference": f"{self.cb}/mec/rnis",
                        "filterCriteriaAssocTri": {"associateId": [{"type": "UE_IPv4_ADDRESS", "value": u}
                                                                   for u in con.get("ues") or []],
                                                   "trigger": ["PERIODICAL_REPORT_STRONGEST_CELLS"]}}
                result = {"subscriptions": [self._subscribe(f"{self.rnis_api}/subscriptions", body)]}
            elif op == "location":
                r = requests.get(f"{self.mec}/{self.loc_api}/queries/users", params={"address": con.get("ue")}, timeout=2)
                users = (r.json().get("userList") or {}).get("user") or []
                result = {"user": users[0] if users else None}
                if users:
                    self._write_location(users[0])
            elif op == "unsubscribe":
                result = {"deleted": [s for s in con.get("subscriptions") or [] if self._unsubscribe(s)]}
            else:
                raise ValueError(f"unknown op {op!r}")
            rsp = {"rqi": rqi, "op": op, "ok": True, "result": result}
        except Exception as e:
            self.stats["errors"] += 1
            rsp = {"rqi": rqi, "op": op, "ok": False, "error": str(e)[:200]}
        rsp["ts"] = int(time.time() * 1000)
        self.c.create_cin(f"{self.root}/responses", rsp)
        return rsp

    def _subscribe(self, path, body):
        r = requests.post(f"{self.mec}/{path}", json=body, timeout=3)
        r.raise_for_status()
        j = r.json()
        inner = next(iter(j.values())) if len(j) == 1 and isinstance(next(iter(j.values())), dict) else j
        href = ((inner.get("_links") or {}).get("self") or {}).get("href", "")
        sid = inner.get("subscriptionId") or href.rsplit("/", 1)[-1]
        self.mec_subs[sid] = href
        return sid

    def _unsubscribe(self, sid):
        href = self.mec_subs.pop(sid, None)
        if not href:
            return False
        try:
            requests.delete(f"{self.mec}{href}" if href.startswith("/") else href, timeout=2)
        except requests.RequestException:
            pass
        return True

    # --- MEC -> oneM2M: events and reports ----------------------------------------------------------------
    def _ue(self, address):
        rn = rn_of(address)
        if address not in self.ues:
            c, lbl = self.c, ["egs:mec/ue", f"egs:id/{address}"]
            c.create_fcnt(self.root, UE_TP, rn, CND.format("device.mecUserEquipment"), {"addr": address}, lbl=lbl)
            c.set_acpi(f"{self.root}/{rn}", *self.acp_read, tp=UE_TP)
            c.create_fcnt(f"{self.root}/{rn}", LOC_TP, "location", CND.format("moduleclass.mecUserLocation"),
                          {"lat": 0.0, "lon": 0.0}, lbl=lbl + ["egs:mec/location"], mni=50)
            c.create_fcnt(f"{self.root}/{rn}", RAD_TP, "radio", CND.format("moduleclass.mecRadioLink"),
                          {"srvCl": "unknown"}, lbl=lbl + ["egs:mec/radio"], mni=100)
            for m, tp in (("location", LOC_TP), ("radio", RAD_TP)):
                c.set_acpi(f"{self.root}/{rn}/{m}", *self.acp_read, tp=tp)
            self.ues.add(address)
        return f"{self.root}/{rn}"

    def on_location_event(self, body, t_rx):
        n = body.get("zoneLocationEventNotification") or body.get("userLocationEventNotification") or {}
        addr = n.get("address")
        if not addr:
            return
        ts = n.get("timeStamp") or {}
        mec_t = ts.get("seconds", 0) + ts.get("nanoSeconds", 0) / 1e9
        ev = {"ue": addr, "zone": n.get("zoneId"), "event": n.get("userLocationEvent"), "poa": n.get("accessPointId"),
              "mec_ts": int(mec_t * 1000), "ipe_ts": int(t_rx * 1000)}
        if n.get("notificationType") == "ZoneLocationEventNotification":
            self.c.create_cin(f"{self.root}/zoneEvents", ev)
            self.stats["zone_events"] += 1
        if ev["event"] in ("ENTERING_AREA_EVENT", "TRANSFERRING_EVENT"):
            self.c.update_fcnt(f"{self._ue(addr)}/location", LOC_TP, {"zonId": ev["zone"], "apId": ev["poa"]})
        self.event_log.append({**ev, "written": time.time()})

    def on_meas_rep(self, n, t_rx):
        addr = next((a.get("value") for a in n.get("associateId") or []), None)
        if not addr:
            return
        nb = sorted(n.get("eutranNeighbourCellMeasInfo") or [], key=lambda m: -(m.get("rsrp") or 0))
        ts = n.get("timeStamp") or {}
        attrs = {"srvCl": (n.get("ecgi") or {}).get("cellId", "unknown"), "rsrp": n.get("rsrp"), "rsrq": n.get("rsrq"),
                 "msTs": int((ts.get("seconds", 0) + ts.get("nanoSeconds", 0) / 1e9) * 1000)}
        if nb:
            attrs.update(nbCl=(nb[0].get("ecgi") or {}).get("cellId"), nbRp=nb[0].get("rsrp"))
        self.c.update_fcnt(f"{self._ue(addr)}/radio", RAD_TP, {k: v for k, v in attrs.items() if v is not None})
        self.stats["radio_reports"] += 1

    def _write_location(self, u):
        li = u.get("locationInfo") or {}
        ts = u.get("timestamp") or {}
        self.c.update_fcnt(f"{self._ue(u['address'])}/location", LOC_TP, {
            "lat": float((li.get("latitude") or [0])[0]), "lon": float((li.get("longitude") or [0])[0]),
            "accy": float(li.get("accuracy") or 0), "zonId": u.get("zoneId"), "apId": u.get("accessPointId"),
            "locTs": int((ts.get("seconds", 0) + ts.get("nanoSeconds", 0) / 1e9) * 1000)})
        self.stats["location_updates"] += 1


class MecServiceClient:
    """oneM2M application side of the bidirectional IPE: request MEC services through oneM2M only."""

    def __init__(self, c: OneM2MClient, root="MEC-IPE"):
        self.c, self.root, self.n = c, root, 0
        self.responses: dict[str, dict] = {}
        self.cv = threading.Condition()

    def on_response(self, con):
        """Feed notifications of <root>/responses here."""
        if isinstance(con, dict) and con.get("rqi"):
            with self.cv:
                self.responses[con["rqi"]] = con
                self.cv.notify_all()

    def call(self, op, timeout=5.0, **args):
        self.n += 1
        rqi = f"{self.c.origin}-{self.n}-{int(time.time() * 1000) % 100000}"
        t0 = time.time()
        self.c.create_cin(f"{self.root}/requests", {"rqi": rqi, "op": op, **args})
        with self.cv:
            self.cv.wait_for(lambda: rqi in self.responses, timeout)
        rsp = self.responses.get(rqi)
        if rsp is None:
            raise OneM2MError(408, "4008", f"no MEC-IPE response to {op}", f"{self.root}/requests")
        rsp["_rtt_ms"] = round((time.time() - t0) * 1000, 1)
        return rsp
