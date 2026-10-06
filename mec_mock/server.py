"""Stand-in for the MEC platform's Location (MEC 013) and RNIS (MEC 012) services.

Serves the subset of the ETSI data models that EdgeGuard reads, so the MEC app
can be tested end to end without the ETSI MEC Sandbox.  Test drivers set the
state through the `/_mock/...` endpoints.

    uvicorn mec_mock.server:app --port 8085
"""
from __future__ import annotations

import time

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="EdgeGuard MEC mock (Location API + RNIS)")
USERS: dict[str, dict] = {}            # address -> {lat, lon, accuracy, zone}
CELLS: dict[str, dict] = {"cell01": {"dl_gbr_prb_usage_cell": 20, "ul_gbr_prb_usage_cell": 10,
                                     "dl_nongbr_prb_usage_cell": 20, "ul_nongbr_prb_usage_cell": 10}}
STATS = {"location_queries": 0, "rnis_queries": 0}


def _ts():
    t = time.time()
    return {"seconds": int(t), "nanoSeconds": int((t % 1) * 1e9)}


@app.get("/location/v3/queries/users")
@app.get("/location/v2/queries/users")
def users(address: list[str] | None = Query(None)):
    STATS["location_queries"] += 1
    now = time.time()
    # a UE the network has not located for 2 s is not reported (no stale fixes)
    sel = [a for a in (address or USERS.keys()) if a in USERS and now - USERS[a]["_t"] <= 2.0]
    out = []
    for a in sel:
        u = USERS[a]
        out.append({
            "address": a, "accessPointId": "ap-site01", "zoneId": u.get("zone", "zone01"),
            "resourceURL": f"/location/v3/queries/users?address={a}", "timestamp": _ts(),
            "locationInfo": {"latitude": [u["lat"]], "longitude": [u["lon"]],
                             "accuracy": u.get("accuracy", 3), "shape": 2},
        })
    return {"userList": {"user": out, "resourceURL": "/location/v3/queries/users"}}


@app.get("/rni/v2/queries/layer2_meas")
def layer2(cell_id: list[str] | None = Query(None)):
    STATS["rnis_queries"] += 1
    sel = [c for c in (cell_id or CELLS.keys()) if c in CELLS]
    return {"timeStamp": _ts(),
            "cellInfo": [{"ecgi": {"cellId": c, "plmn": {"mcc": "450", "mnc": "05"}}, **CELLS[c]}
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


@app.get("/_mock/stats")
def stats():
    return JSONResponse(STATS)
