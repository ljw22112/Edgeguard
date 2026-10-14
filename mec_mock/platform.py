"""MEC platform services of the mock, beyond Location queries and RNIS (mec_mock/server.py includes this router):

* MEC 011 (Mp1) application enablement: confirm_ready, service registration / discovery, service
  availability subscriptions - how a MEC app announces its service and finds the platform's services;
* MEC 021 Application Mobility Service (AMS): registration of an app instance's UEs, mobility procedure
  subscriptions; when a registered UE moves to another MEC host's zone, the source instance gets
  INTERHOST_MOVEOUT_TRIGGERED with the target instance, transfers the user context, reports
  USER_CONTEXT_TRANSFER_COMPLETED, and AMS confirms INTERHOST_MOVEOUT_COMPLETED;
* MEC 013 area (circle geofence) and distance subscriptions: ENTERING / LEAVING a circle, two UEs
  closer than a distance (ALL_WITHIN_DISTANCE).

Subset of the ETSI data models that EdgeGuard uses; enough to exercise the integration end to end.
"""
from __future__ import annotations

import itertools
import math
import threading
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()
_ids = itertools.count(1)
SERVICES: dict[str, dict] = {}         # serInstanceId -> ServiceInfo (+ owner appInstanceId)
READY: dict[str, dict] = {}            # appInstanceId -> {"indication": "READY", "t": ...}
SER_SUBS: dict[str, dict] = {}         # service availability subscriptions
AMS_REG: dict[str, dict] = {}          # appMobilityServiceId -> RegistrationInfo
AMS_SUBS: dict[str, dict] = {}         # mobility procedure subscriptions
GEO_SUBS: dict[str, dict] = {}         # area / distance subscriptions (MEC 013)
LOG: list[dict] = []                   # every platform notification (test drivers read it)
_ctx = {"users": None, "post": None, "host_of_zone": {}}


def init(known_users, post, host_of_zone=None, loop=True):
    """known_users() -> {address: {lat, lon, zone, ...}}; post(url, body) sends a notification;
    host_of_zone: zone -> MEC host name (AMS decides inter-host moves with it)."""
    _ctx.update(users=known_users, post=post, host_of_zone=dict(host_of_zone or {}))
    # the platform's own services, discoverable over Mp1 (endpoints relative to the platform base URL)
    for name, uri, cat in (("LocationService", "/location/v3", "Location"), ("RNIS", "/rni/v2", "RNI"),
                           ("AppMobilityService", "/amsi/v1", "AMS")):
        sid = f"ser{next(_ids)}"
        SERVICES[sid] = {"serInstanceId": sid, "serName": name, "state": "ACTIVE", "version": "3.1.1",
                         "serCategory": {"href": "", "id": cat.lower(), "name": cat, "version": "v3"},
                         "transportInfo": {"id": f"{name}-rest", "name": "REST", "type": "REST_HTTP", "protocol": "HTTP",
                                           "version": "1.1", "endpoint": {"uris": [uri]}},
                         "serializer": "JSON", "scopeOfLocality": "MEC_SYSTEM", "_app": "mec-platform"}
    if loop:
        threading.Thread(target=_loop, daemon=True).start()


def _ts():
    t = time.time()
    return {"seconds": int(t), "nanoSeconds": int((t % 1) * 1e9)}


def _notify(url, body, kind):
    LOG.append({"t": time.time(), "kind": kind, "body": body})
    if url and _ctx["post"]:
        _ctx["post"](url, body)


# --- MEC 011 (Mp1) -----------------------------------------------------------------------------------------
@router.post("/mec_app_support/v2/applications/{app}/confirm_ready", status_code=204)
async def confirm_ready(app: str, req: Request):
    READY[app] = {**(await req.json()), "t": time.time()}
    return Response(status_code=204)


@router.post("/mec_service_mgmt/v1/applications/{app}/services", status_code=201)
async def register_service(app: str, req: Request):
    info = await req.json()
    sid = f"ser{next(_ids)}"
    SERVICES[sid] = {**info, "serInstanceId": sid, "state": info.get("state", "ACTIVE"), "_app": app}
    _availability(SERVICES[sid], "ADDED")
    return {k: v for k, v in SERVICES[sid].items() if not k.startswith("_")}


@router.delete("/mec_service_mgmt/v1/applications/{app}/services/{sid}", status_code=204)
def deregister_service(app: str, sid: str):
    s = SERVICES.pop(sid, None)
    if s:
        _availability(s, "REMOVED")
    return Response(status_code=204)


@router.get("/mec_service_mgmt/v1/services")
def discover(ser_name: str | None = None):
    return [{k: v for k, v in s.items() if not k.startswith("_")} for s in SERVICES.values()
            if ser_name is None or s.get("serName") == ser_name]


@router.post("/mec_service_mgmt/v1/applications/{app}/subscriptions", status_code=201)
async def ser_subscribe(app: str, req: Request):
    b = await req.json()
    sid = f"sas{next(_ids)}"
    SER_SUBS[sid] = {**b, "_app": app}
    return {**b, "_links": {"self": {"href": f"/mec_service_mgmt/v1/applications/{app}/subscriptions/{sid}"}}}


def _availability(s, change):
    names = None
    for sub in SER_SUBS.values():
        names = ((sub.get("filteringCriteria") or {}).get("serNames")) or None
        if names and s.get("serName") not in names:
            continue
        _notify(sub.get("callbackReference"), {"notificationType": "SerAvailabilityNotification",
                                               "serviceReferences": [{"serName": s.get("serName"),
                                                                      "serInstanceId": s["serInstanceId"],
                                                                      "state": s.get("state"), "changeType": change}]},
                "ser_availability")


# --- MEC 021 AMS -------------------------------------------------------------------------------------------
@router.post("/amsi/v1/app_mobility_services", status_code=201)
async def ams_register(req: Request):
    b = await req.json()
    sid = f"ams{next(_ids)}"
    AMS_REG[sid] = {**b, "appMobilityServiceId": sid}
    return AMS_REG[sid]


@router.put("/amsi/v1/app_mobility_services/{sid}")
async def ams_update(sid: str, req: Request):
    if sid not in AMS_REG:
        return JSONResponse({"detail": "not found"}, status_code=404)
    b = await req.json()
    AMS_REG[sid].update(b)
    # context transfer reported complete -> the move-out is complete
    for d in b.get("deviceInformation") or []:
        if d.get("contextTransferState") == "USER_CONTEXT_TRANSFER_COMPLETED":
            ue = (d.get("associateId") or {}).get("value")
            app = (AMS_REG[sid].get("serviceConsumerId") or {}).get("appInstanceId")
            _mobility(ue, "INTERHOST_MOVEOUT_COMPLETED", app, None)
    return AMS_REG[sid]


@router.post("/amsi/v1/subscriptions", status_code=201)
async def ams_subscribe(req: Request):
    b = await req.json()
    sid = f"amss{next(_ids)}"
    AMS_SUBS[sid] = b
    return {**b, "_links": {"self": {"href": f"/amsi/v1/subscriptions/{sid}"}}}


def _instances_for(ue):
    """appInstanceId -> host for every app instance that registered this UE with AMS."""
    out = {}
    for r in AMS_REG.values():
        if any((d.get("associateId") or {}).get("value") == ue for d in r.get("deviceInformation") or []):
            c = r.get("serviceConsumerId") or {}
            out[c.get("appInstanceId")] = c.get("mecHost") or r.get("mecHost")
    return out


def _mobility(ue, status, source_app, target):
    for sub in AMS_SUBS.values():
        fc = sub.get("filterCriteria") or {}
        if fc.get("appInstanceId") and fc["appInstanceId"] != source_app:
            continue
        if fc.get("mobilityStatus") and status not in fc["mobilityStatus"]:
            continue
        body = {"notificationType": "MobilityProcedureNotification", "timeStamp": _ts(),
                "associateId": [{"type": "UE_IPv4_ADDRESS", "value": ue}], "mobilityStatus": status}
        if target:
            body["targetAppInfo"] = target
        _notify(sub.get("callbackReference"), body, "ams")


# --- MEC 013 area and distance subscriptions -------------------------------------------------------------------
@router.post("/location/v3/subscriptions/area", status_code=201)
async def area_subscribe(req: Request):
    b = (await req.json()).get("userAreaSubscription") or {}
    sid = f"area{next(_ids)}"
    GEO_SUBS[sid] = {"kind": "area", "body": b, "inside": {}}
    return {"userAreaSubscription": {**b, "_links": {"self": {"href": f"/location/v3/subscriptions/area/{sid}"}}}}


@router.post("/location/v3/subscriptions/distance", status_code=201)
async def distance_subscribe(req: Request):
    b = (await req.json()).get("userDistanceSubscription") or {}
    sid = f"dist{next(_ids)}"
    GEO_SUBS[sid] = {"kind": "distance", "body": b, "within": False}
    return {"userDistanceSubscription": {**b, "_links": {"self": {"href": f"/location/v3/subscriptions/distance/{sid}"}}}}


@router.delete("/location/v3/subscriptions/area/{sid}", status_code=204)
@router.delete("/location/v3/subscriptions/distance/{sid}", status_code=204)
@router.delete("/amsi/v1/subscriptions/{sid}", status_code=204)
def geo_unsubscribe(sid: str):
    GEO_SUBS.pop(sid, None)
    AMS_SUBS.pop(sid, None)
    return Response(status_code=204)


@router.get("/_mock/platform")
def platform_state():
    return {"ready": READY, "services": list(SERVICES), "ams_registrations": list(AMS_REG),
            "subscriptions": {"ser": list(SER_SUBS), "ams": list(AMS_SUBS), "geo": list(GEO_SUBS)},
            "log": [{"t": e["t"], "kind": e["kind"], "status": e["body"].get("mobilityStatus")
                     or e["body"].get("distanceEvent") or e["body"].get("userLocationEvent")} for e in LOG]}


def _metres(a, b):
    k = math.pi / 180 * 6378137.0
    return math.hypot((a["lon"] - b["lon"]) * k * math.cos(math.radians(a["lat"])), (a["lat"] - b["lat"]) * k)


def _loop(period=0.2):
    last_zone: dict[str, str] = {}
    while True:
        time.sleep(period)
        try:
            step(last_zone)
        except Exception:          # noqa: BLE001 - keep the platform running
            pass


def step(last_zone):
    """One pass of the network side: AMS move-outs and geofence / distance events."""
    users = _ctx["users"]() if _ctx["users"] else {}
    # AMS: a registered UE changes MEC host -> move-out triggered for the source instance
    for ue, u in users.items():
        z, prev = u.get("zone"), last_zone.get(ue)
        last_zone[ue] = z
        if prev is None or z == prev or not z:
            continue
        hz = _ctx["host_of_zone"]
        src_host, dst_host = hz.get(prev), hz.get(z)
        if not src_host or src_host == dst_host:
            continue
        inst = _instances_for(ue)
        src = next((a for a, h in inst.items() if h == src_host), None)
        dst = next((a for a, h in inst.items() if h == dst_host), None)
        if src:
            target = {"appInstanceId": dst, "mecHost": dst_host}
            reg = next((r for r in AMS_REG.values() if (r.get("serviceConsumerId") or {}).get("appInstanceId") == dst), None)
            if reg and reg.get("commInterface"):
                target["commInterface"] = reg["commInterface"]
            _mobility(ue, "INTERHOST_MOVEOUT_TRIGGERED", src, target)
    # MEC 013 geofences
    for g in list(GEO_SUBS.values()):
        b = g["body"]
        cb = (b.get("callbackReference") or {}).get("notifyURL") if isinstance(b.get("callbackReference"), dict) \
            else b.get("callbackReference")
        if g["kind"] == "area":
            area = b.get("areaDefine") or {}
            c = (area.get("points") or [{}])[0]
            centre = {"lat": c.get("latitude"), "lon": c.get("longitude")}
            for a in b.get("addressList") or list(users):
                u = users.get(a)
                if not u or centre["lat"] is None:
                    continue
                inside = _metres(u, centre) <= float(area.get("radius", 0))
                was = g["inside"].get(a)
                g["inside"][a] = inside
                if was is None or was == inside:
                    continue
                ev = "ENTERING_AREA_EVENT" if inside else "LEAVING_AREA_EVENT"
                if ev in (b.get("locationEventCriteria") or [ev]):
                    _notify(cb, {"userAreaNotification": {
                        "notificationType": "UserAreaNotification", "timeStamp": _ts(), "address": a,
                        "userLocationEvent": ev, "locationInfo": {"latitude": [u["lat"]], "longitude": [u["lon"]]}}},
                        "area")
        else:
            mon = b.get("monitoredAddress") or []
            if len(mon) != 2 or mon[0] not in users or mon[1] not in users:
                continue
            d = _metres(users[mon[0]], users[mon[1]])
            within = d <= float(b.get("distance", 0))
            if within and not g["within"]:
                _notify(cb, {"userDistanceNotification": {
                    "notificationType": "UserDistanceNotification", "timeStamp": _ts(),
                    "distanceEvent": "ALL_WITHIN_DISTANCE",
                    "monitoredUsers": {"user": [{"address": a, "locationInfo": {
                        "latitude": [users[a]["lat"]], "longitude": [users[a]["lon"]]}} for a in mon]},
                    "_distance_m": round(d, 2)}}, "distance")
            g["within"] = within
