"""Stand-in for the MEC platform's Location (MEC 013) and RNIS (MEC 012) services.

Serves the subset of the ETSI data models that EdgeGuard reads, so the MEC app
can be tested end to end without the ETSI MEC Sandbox.  Test drivers set the
state through the `/_mock/...` endpoints, or the mock plays a Sandbox scenario:

    uvicorn mec_mock.server:app --port 8085
    MEC_MOCK_SCENARIO=scenarios/edgeguard-warehouse.yaml MEC_MOCK_GIS_PERIOD=1.0 \
        uvicorn mec_mock.server:app --port 8085
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="EdgeGuard MEC mock (Location API + RNIS)")
USERS: dict[str, dict] = {}            # address -> {lat, lon, accuracy, zone}
CELLS: dict[str, dict] = {"cell01": {"dl_gbr_prb_usage_cell": 20, "ul_gbr_prb_usage_cell": 10,
                                     "dl_nongbr_prb_usage_cell": 20, "ul_nongbr_prb_usage_cell": 10}}
STATS = {"location_queries": 0, "rnis_queries": 0}
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
