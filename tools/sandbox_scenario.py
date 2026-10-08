"""Generate an ETSI MEC Sandbox scenario of the EdgeGuard warehouse.

    python tools/sandbox_scenario.py --out scenarios/edgeguard-warehouse.yaml

The MEC Sandbox (AdvantEDGE scenario format, version 1.8.0) moves every UE along a GeoJSON
path at a constant velocity (m/s) and serves the positions through the Location API
(MEC 013) and, through MEC-IPE, as oneM2M resources.  The organizers encourage teams to
build their own scenarios with their own maps and tracks; this one is our warehouse:

  40 m x 24 m, cross aisle at y = 12, picking aisles at x = 6, 14, 22, 30,
  private 5G with two small cells (west / east halves), one MEC host.

  forklift_01  loop: cross aisle eastbound, back along the south wall    2.5 m/s
  forklift_02  back and forth in aisle x = 22                             2.0 m/s
  worker_01    back and forth in aisle x = 14 -> meets forklift_01 every loop  1.4 m/s
  worker_02    picking beside the cross aisle (1.5 m off its centre)     0.6 m/s
  worker_03    back and forth in aisle x = 22 -> head-on with forklift_02 1.0 m/s
  worker_04    aisle x = 36, no forklift traffic (background)             1.0 m/s

The track table is also used by mec_mock (local stand-in for the Sandbox) and the tests.
Coordinates: site metres, x = east, y = north, around mec_services.origin in config/site.yaml.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import uuid

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.mec_services import SiteFrame                    # noqa: E402

SITE_W, SITE_H = 40.0, 24.0

# device id -> (UE name / Location API address, kind, track [(x, y)...], eopMode, velocity m/s)
TRACKS = {
    "forklift_01": ("10.100.0.11", "forklift", [(2, 12), (38, 12), (38, 2), (2, 2), (2, 12)], "LOOP", 2.5),
    "forklift_02": ("10.100.0.12", "forklift", [(22, 3), (22, 21)], "REVERSE", 2.0),
    "worker_01": ("10.100.0.1", "worker", [(14, 3), (14, 20)], "REVERSE", 1.4),
    "worker_02": ("10.100.0.2", "worker", [(26, 13.5), (34, 13.5)], "REVERSE", 0.6),
    "worker_03": ("10.100.0.3", "worker", [(22, 20), (22, 6)], "REVERSE", 1.0),
    "worker_04": ("10.100.0.4", "worker", [(36, 16), (36, 22)], "REVERSE", 1.0),
}
CELLS = {  # POA name -> (zone, (x, y), cellId)
    "poa-5g-west": ("warehouse-west", (10, 12), "500000101"),
    "poa-5g-east": ("warehouse-east", (30, 12), "500000102"),
}
MEC_HOST = ("mec-edge", "warehouse-west", (2, 22))


def _uid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"edgeguard/{name}"))


def _net(lat=None, lat_var=None):
    return {"latency": lat, "latencyVariation": lat_var, "throughputDl": 1000, "throughputUl": 1000,
            "latencyDistribution": None, "throughput": None, "packetLoss": None}


def _point(frame, xy):
    lat, lon = frame.to_latlon(*xy)
    return {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}


def nearest_cell(xy):
    return min(CELLS, key=lambda c: (CELLS[c][1][0] - xy[0]) ** 2 + (CELLS[c][1][1] - xy[1]) ** 2)


def ue(frame, dev):
    name, kind, track, eop, v = TRACKS[dev]
    lonlat = [_point(frame, p)["coordinates"] for p in track]
    return {
        "id": _uid(dev), "name": name, "type": "UE",
        "geoData": {"location": {"type": "Point", "coordinates": lonlat[0]},
                    "path": {"type": "LineString", "coordinates": lonlat},
                    "eopMode": eop, "velocity": v, "radius": None},
        "connected": True, "wireless": True, "wirelessType": "5g",
        "dataNetwork": {"dnn": None, "ladn": None, "ecsp": None},
        "netChar": _net(), "macId": None, "isExternal": None, "networkLocationsInRange": None,
        "meta": {"edgeguard.device": dev, "edgeguard.kind": kind}, "userMeta": None, "processes": [],
        "linkLatency": None, "linkLatencyVariation": None, "linkThroughput": None, "linkPacketLoss": None,
    }


def poa(frame, name, ues):
    zone, xy, cell = CELLS[name]
    return {
        "id": _uid(name), "name": name, "type": "POA-5G", "netChar": _net(1, 1),
        "poa5GConfig": {"cellId": cell},
        "geoData": {"location": _point(frame, xy), "radius": 30, "path": None, "eopMode": None, "velocity": None},
        "terminalLinkLatency": None, "terminalLinkLatencyVariation": None, "terminalLinkThroughput": None,
        "terminalLinkPacketLoss": None, "meta": None, "userMeta": None, "cellularPoaConfig": None,
        "poa4GConfig": None, "poaWifiConfig": None, "physicalLocations": ues,
    }


def default_nl(name, pls=None):
    return {"id": _uid(name), "name": name, "type": "DEFAULT", "netChar": _net(1, 1),
            "terminalLinkLatency": None, "terminalLinkLatencyVariation": None, "terminalLinkThroughput": None,
            "terminalLinkPacketLoss": None, "meta": None, "userMeta": None, "cellularPoaConfig": None,
            "poa4GConfig": None, "poa5GConfig": None, "poaWifiConfig": None, "geoData": None,
            "physicalLocations": pls or []}


def zone(name, ztype, nls, color=None):
    z = {"id": _uid(name), "name": name, "type": ztype, "netChar": _net(5, 1),
         "meta": {"display.map.color": color} if color else None, "userMeta": None, "networkLocations": nls}
    for k in ("interFog", "interEdge", "edgeFog"):
        for s in ("Latency", "LatencyVariation", "Throughput", "PacketLoss"):
            z[k + s] = None
    return z


def build(frame, name="edgeguard-warehouse"):
    by_cell = {c: [] for c in CELLS}
    for dev, (_, _, track, _, _) in TRACKS.items():
        by_cell[nearest_cell(track[0])].append(ue(frame, dev))
    edge = {"id": _uid(MEC_HOST[0]), "name": MEC_HOST[0], "type": "EDGE",
            "geoData": {"location": _point(frame, MEC_HOST[2]), "radius": None, "path": None,
                        "eopMode": None, "velocity": None},
            "connected": True, "dataNetwork": {"dnn": None, "ladn": None, "ecsp": None}, "processes": [],
            "netChar": _net(), "isExternal": None, "networkLocationsInRange": None, "wireless": None,
            "wirelessType": None, "meta": None, "userMeta": None}
    zones = [zone("factory-operator-COMMON", "COMMON", [default_nl("factory-operator-COMMON-DEFAULT")])]
    colors = {"warehouse-west": "#E49C0C", "warehouse-east": "#00A0FF"}
    for zname in dict.fromkeys(z for z, _, _ in CELLS.values()):
        nls = [default_nl(f"{zname}-DEFAULT", [copy.deepcopy(edge)] if zname == MEC_HOST[1] else [])]
        nls += [poa(frame, c, by_cell[c]) for c, (z, _, _) in CELLS.items() if z == zname]
        zones.append(zone(zname, "ZONE", nls, colors.get(zname)))
    public = {"id": "PUBLIC", "name": "PUBLIC", "type": "PUBLIC", "netChar": _net(6, 2),
              "interZoneLatency": None, "interZoneLatencyVariation": None, "interZoneThroughput": None,
              "interZonePacketLoss": None, "meta": None, "userMeta": None, "cellularDomainConfig": None,
              "zones": [zone("PUBLIC-COMMON", "COMMON", [default_nl("PUBLIC-COMMON-DEFAULT")])]}
    operator = {"id": _uid("factory-operator"), "name": "factory-operator", "type": "OPERATOR-CELLULAR",
                "netChar": _net(6, 2), "interZoneLatency": None, "interZoneLatencyVariation": None,
                "interZoneThroughput": None, "interZonePacketLoss": None, "meta": None, "userMeta": None,
                "cellularDomainConfig": {"mnc": "001", "mcc": "001", "defaultCellId": "FFFFFFF"},
                "zones": zones}
    return {"version": "1.8.0", "name": name, "id": None,
            "description": "EdgeGuard warehouse: forklift / worker encounters on private 5G (oneM2M Hackathon 2026)",
            "config": None,
            "deployment": {"netChar": _net(50, 10), "interDomainLatency": None,
                           "interDomainLatencyVariation": None, "interDomainThroughput": None,
                           "interDomainPacketLoss": None, "meta": None, "userMeta": None,
                           # required by the AdvantEDGE / MEC Sandbox validator (v1.9: "connectivity == nil")
                           "connectivity": {"model": "OPEN"},
                           "d2d": {"d2dMaxDistance": 100, "disableD2dViaNetwork": False},
                           "domains": [public, operator]}}


def ue_map():
    """Location API address -> {"id", "kind"} (config mec_services.ue_map)."""
    return {name: {"id": dev, "kind": kind} for dev, (name, kind, _, _, _) in TRACKS.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(ROOT, "config", "site.yaml"))
    ap.add_argument("--out", default=os.path.join(ROOT, "scenarios", "edgeguard-warehouse.yaml"))
    a = ap.parse_args()
    o = yaml.safe_load(open(a.config))["mec_services"]["origin"]
    sc = build(SiteFrame(o["lat"], o["lon"]))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        yaml.safe_dump(sc, fh, sort_keys=False)
    with open(os.path.splitext(a.out)[0] + ".json", "w") as fh:
        json.dump(sc, fh, indent=1)
    print("wrote", a.out, "and .json;", len(TRACKS), "UEs,", len(CELLS), "cells")


if __name__ == "__main__":
    main()
