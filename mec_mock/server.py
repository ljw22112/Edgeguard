"""Stand-in for the MEC platform's Location (MEC 013) and RNIS (MEC 012) services.

Serves the subset of the ETSI data models that EdgeGuard reads, so the MEC app
can be tested end to end without the ETSI MEC Sandbox.  Test drivers set the
state through the `/_mock/...` endpoints, or the mock plays a Sandbox scenario:

    uvicorn mec_mock.server:app --port 8085
    MEC_MOCK_SCENARIO=scenarios/edgeguard-warehouse.yaml MEC_MOCK_GIS_PERIOD=1.0 \
        uvicorn mec_mock.server:app --port 8085
"""
from __future__ import annotations

import itertools
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="EdgeGuard MEC mock (Location API + RNIS)")
USERS: dict[str, dict] = {}            # address -> {lat, lon, accuracy, zone}
CELLS: dict[str, dict] = {"cell01": {"dl_gbr_prb_usage_cell": 20, "ul_gbr_prb_usage_cell": 10,
                                     "dl_nongbr_prb_usage_cell": 20, "ul_nongbr_prb_usage_cell": 10}}
STATS = {"location_queries": 0, "rnis_queries": 0, "notifications": 0, "notification_errors": 0}
# MEC 013 zone / user location event subscriptions and MEC 012 MeasRepUe subscriptions
SUBS: dict[str, dict] = {}
_sub_id = itertools.count(1)
EVENTS: list[dict] = []                # every zone / user event the network detected (test drivers read it)
_pool = ThreadPoolExecutor(8)
PLAYER = None
if os.environ.get("MEC_MOCK_SCENARIO"):
    from mec_mock.scenario_player import ScenarioPlayer
    PLAYER = ScenarioPlayer.load(os.environ["MEC_MOCK_SCENARIO"],
                                 period=float(os.environ.get("MEC_MOCK_GIS_PERIOD", "1.0")),
                                 accuracy=float(os.environ.get("MEC_MOCK_ACCURACY", "1.0")),
                                 noise=float(os.environ.get("MEC_MOCK_NOISE", "0")))
    CELLS.clear()


def _ts():
    t = time.time()
    return {"seconds": int(t), "nanoSeconds": int((t % 1) * 1e9)}


@app.get("/location/v3/queries/users")
@app.get("/location/v2/queries/users")
def users(address: list[str] | None = Query(None)):
    STATS["location_queries"] += 1
    now = time.time()
    known = dict(PLAYER.users()) if PLAYER else {}
    # a UE the network has not located for 2 s is not reported (no stale fixes)
    known.update({a: u for a, u in USERS.items() if now - u["_t"] <= 2.0})
    sel = [a for a in (address or known.keys()) if a in known]
    out = []
    for a in sel:
        u = known[a]
        ts = u.get("ts")
        out.append({
            "address": a, "accessPointId": u.get("poa") or "ap-site01", "zoneId": u.get("zone") or "zone01",
            "resourceURL": f"/location/v3/queries/users?address={a}",
            "timestamp": {"seconds": int(ts), "nanoSeconds": int((ts % 1) * 1e9)} if ts else _ts(),
            "locationInfo": {"latitude": [u["lat"]], "longitude": [u["lon"]],
                             "accuracy": u.get("accuracy", 3), "shape": 2},
        })
    return {"userList": {"user": out, "resourceURL": "/location/v3/queries/users"}}


@app.get("/rni/v2/queries/layer2_meas")
def layer2(cell_id: list[str] | None = Query(None)):
    STATS["rnis_queries"] += 1
    cells = dict(PLAYER.cell_loads()) if PLAYER else {}
    cells.update(CELLS)
    sel = [c for c in (cell_id or cells.keys()) if c in cells]
    return {"timeStamp": _ts(),
            "cellInfo": [{"ecgi": {"cellId": c, "plmn": {"mcc": "001", "mnc": "001"}}, **cells[c]}
                         for c in sel]}


@app.post("/_mock/users/{address}")
async def set_user(address: str, req: Request):
    USERS[address] = await req.json() | {"_t": time.time()}
    return {"ok": True}


@app.delete("/_mock/users/{address}")
def del_user(address: str):
    USERS.pop(address, None)
    return {"ok": True}


@app.post("/_mock/cells/{cell}")
async def set_cell(cell: str, req: Request):
    CELLS[cell] = await req.json()
    return {"ok": True}


@app.get("/_mock/scenario")
def scenario():
    return {"name": PLAYER.name if PLAYER else None, "period_s": PLAYER.period if PLAYER else None,
            "t0": PLAYER.t0 if PLAYER else None,
            "ues": PLAYER.users() if PLAYER else {}}


@app.get("/_mock/stats")
def stats():
    return JSONResponse(STATS)


# --- subscriptions (MEC 013 v3 zone / user location events, MEC 012 v2 MeasRepUe) ------------------------
def _new_sub(kind, body, callback):
    sid = f"sub{next(_sub_id)}"
    api = "rni/v2" if kind == "meas_rep_ue" else "location/v3"
    path = f"/{api}/subscriptions/{'zones' if kind == 'zone' else 'users' if kind == 'user' else ''}".rstrip("/")
    SUBS[sid] = {"kind": kind, "body": body, "callback": callback, "url": f"{path}/{sid}"}
    return sid, SUBS[sid]["url"]


@app.post("/location/v3/subscriptions/zones", status_code=201)
async def sub_zone(req: Request):
    b = (await req.json()).get("zoneLocationEventSubscription") or {}
    cb = (b.get("callbackReference") or {}).get("notifyURL") if isinstance(b.get("callbackReference"), dict) \
        else b.get("callbackReference")
    sid, url = _new_sub("zone", b, cb)
    return {"zoneLocationEventSubscription": {**b, "_links": {"self": {"href": url}}, "subscriptionId": sid}}


@app.post("/location/v3/subscriptions/users", status_code=201)
async def sub_user(req: Request):
    b = (await req.json()).get("userLocationEventSubscription") or {}
    cb = (b.get("callbackReference") or {}).get("notifyURL") if isinstance(b.get("callbackReference"), dict) \
        else b.get("callbackReference")
    sid, url = _new_sub("user", b, cb)
    return {"userLocationEventSubscription": {**b, "_links": {"self": {"href": url}}, "subscriptionId": sid}}


@app.post("/rni/v2/subscriptions", status_code=201)
async def sub_rnis(req: Request):
    b = await req.json()
    if b.get("subscriptionType") != "MeasRepUeSubscription":
        return JSONResponse({"detail": "only MeasRepUeSubscription"}, status_code=400)
    sid, url = _new_sub("meas_rep_ue", b, b.get("callbackReference"))
    return {**b, "_links": {"self": {"href": url}}, "subscriptionId": sid}


@app.delete("/location/v3/subscriptions/zones/{sid}", status_code=204)
@app.delete("/location/v3/subscriptions/users/{sid}", status_code=204)
@app.delete("/rni/v2/subscriptions/{sid}", status_code=204)
def unsubscribe(sid: str):
    SUBS.pop(sid, None)


@app.get("/_mock/events")
def events(since: float = 0.0):
    return [e for e in EVENTS if e["t"] > since]


@app.get("/_mock/radio")
def radio():
    return PLAYER.radio() if PLAYER else {}


def _post(url, body):
    try:
        requests.post(url, json=body, timeout=2)
        STATS["notifications"] += 1
    except requests.RequestException:
        STATS["notification_errors"] += 1


def _known_users():
    now = time.time()
    known = dict(PLAYER.users()) if PLAYER else {}
    known.update({a: u for a, u in USERS.items() if now - u["_t"] <= 2.0})
    return known


def _event_loop(period=0.2):
    """The network side: detects zone / access-point changes of every UE and notifies subscribers;
    sends MeasRepUe reports for subscribed UEs once per GIS period."""
    from mec_mock.scenario_player import rsrp_index, rsrq_index
    last, last_rep = {}, 0.0
    while True:
        time.sleep(period)
        try:
            users, now = _known_users(), time.time()
            for a, u in users.items():
                prev = last.get(a)
                cur = (u.get("zone"), u.get("poa"))
                last[a] = cur
                if prev is None or prev == cur:
                    continue
                ts = _ts()
                for ev, zone in (("LEAVING_AREA_EVENT", prev[0]), ("ENTERING_AREA_EVENT", cur[0])):
                    if not zone or prev[0] == cur[0]:
                        continue
                    EVENTS.append({"t": now, "address": a, "zoneId": zone, "event": ev, "poa": cur[1]})
                    for s in list(SUBS.values()):
                        b = s["body"]
                        if s["kind"] == "zone" and b.get("zoneId") == zone and ev in (b.get("locationEventCriteria") or [ev]) \
                                and (not b.get("addressList") or a in b["addressList"]):
                            _pool.submit(_post, s["callback"], {"zoneLocationEventNotification": {
                                "notificationType": "ZoneLocationEventNotification", "timeStamp": ts, "address": a,
                                "zoneId": zone, "accessPointId": cur[1], "userLocationEvent": ev,
                                "_links": {"subscription": {"href": s["url"]}}}})
                for s in list(SUBS.values()):
                    b = s["body"]
                    if s["kind"] == "user" and b.get("address") == a:
                        _pool.submit(_post, s["callback"], {"userLocationEventNotification": {
                            "notificationType": "UserLocationEventNotification", "timeStamp": ts, "address": a,
                            "zoneId": cur[0], "accessPointId": cur[1], "userLocationEvent": "TRANSFERRING_EVENT",
                            "_links": {"subscription": {"href": s["url"]}}}})
            if PLAYER and now - last_rep >= PLAYER.period:
                last_rep = now
                rad = PLAYER.radio()
                for s in list(SUBS.values()):
                    if s["kind"] != "meas_rep_ue":
                        continue
                    ids = [x.get("value") for x in ((s["body"].get("filterCriteriaAssocTri") or {}).get("associateId") or [])]
                    for a in ids:
                        if a not in rad or a not in users:
                            continue
                        serving = users[a].get("cell")
                        cells = rad[a]
                        if serving not in cells:
                            continue
                        nb = [c for c in cells if c != serving]
                        _pool.submit(_post, s["callback"], {
                            "notificationType": "MeasRepUeNotification", "timeStamp": _ts(),
                            "associateId": [{"type": "UE_IPv4_ADDRESS", "value": a}],
                            "ecgi": {"cellId": serving, "plmn": {"mcc": "001", "mnc": "001"}},
                            "rsrp": rsrp_index(cells[serving]), "rsrq": rsrq_index(cells[serving], [cells[c] for c in nb]),
                            "trigger": "PERIODICAL_REPORT_STRONGEST_CELLS",
                            "eutranNeighbourCellMeasInfo": [{"ecgi": {"cellId": c, "plmn": {"mcc": "001", "mnc": "001"}},
                                                             "rsrp": rsrp_index(cells[c]),
                                                             "rsrq": rsrq_index(cells[c], [cells[o] for o in cells if o != c])}
                                                            for c in nb]})
        except Exception:                                      # keep the network running
            STATS["notification_errors"] += 1


threading.Thread(target=_event_loop, daemon=True).start()

# MEC 011 (Mp1), MEC 021 (AMS), MEC 013 area / distance subscriptions (mec_mock/platform.py); zone -> MEC host
# from the MEC_MOCK_HOSTS environment variable, e.g. "zoneA=mep-a,zoneB=mep-b"
from mec_mock import platform as _platform   # noqa: E402
_platform.init(_known_users, _post, dict(kv.split("=", 1) for kv in os.environ.get("MEC_MOCK_HOSTS", "").split(",") if "=" in kv))
app.include_router(_platform.router)


@app.get("/_mock/subscriptions")
def subscriptions():
    return {sid: {"kind": s["kind"], "callback": s["callback"]} for sid, s in SUBS.items()}
