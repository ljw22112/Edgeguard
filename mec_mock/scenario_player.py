"""Plays an ETSI MEC Sandbox (AdvantEDGE 1.8.0) scenario the way the Sandbox's GIS engine does:
every UE moves along its GeoJSON path at its velocity (m/s), LOOP or REVERSE at the end,
and attaches to the nearest POA in range.  Positions are refreshed every `period` seconds
(the Sandbox updates UE positions about once a second), so what the Location API returns
is as coarse in time as on the real Sandbox.
"""
from __future__ import annotations

import bisect
import math
import random
import zlib
import time

import yaml

EARTH_R = 6378137.0


class _Frame:
    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        self.ky = math.pi / 180 * EARTH_R
        self.kx = self.ky * math.cos(math.radians(lat0))

    def xy(self, lon, lat):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def lonlat(self, x, y):
        return (self.lon0 + x / self.kx, self.lat0 + y / self.ky)


class _Ue:
    def __init__(self, pl, frame):
        g = pl.get("geoData") or {}
        coords = ((g.get("path") or {}).get("coordinates")) or [g["location"]["coordinates"]]
        self.name, self.meta = pl["name"], pl.get("meta") or {}
        self.pts = [frame.xy(*c) for c in coords]
        self.s = [0.0]
        for (x0, y0), (x1, y1) in zip(self.pts, self.pts[1:]):
            self.s.append(self.s[-1] + math.hypot(x1 - x0, y1 - y0))
        self.v = float(g.get("velocity") or 0.0)
        self.eop = g.get("eopMode") or "LOOP"

    def pos(self, t):
        L = self.s[-1]
        if L <= 0 or self.v <= 0:
            return self.pts[0]
        d = self.v * t
        if self.eop == "REVERSE":
            d %= 2 * L
            d = d if d <= L else 2 * L - d
        else:
            d %= L
        i = max(0, min(len(self.s) - 2, bisect.bisect_right(self.s, d) - 1))
        seg = self.s[i + 1] - self.s[i]
        a = 0.0 if seg <= 0 else (d - self.s[i]) / seg
        (x0, y0), (x1, y1) = self.pts[i], self.pts[i + 1]
        return (x0 + a * (x1 - x0), y0 + a * (y1 - y0))


class ScenarioPlayer:
    def __init__(self, scenario: dict, period=1.0, t0=None, accuracy=1.0, noise=0.0):
        """noise: std-dev (m) of a Gaussian error added to each fix (0 = exact scenario
        positions, as the Sandbox's GIS engine reports them; > 0 models a real network)."""
        self.name, self.period, self.accuracy, self.noise = scenario.get("name"), period, accuracy, noise
        self.t0 = time.time() if t0 is None else t0
        ues, poas = [], []
        for dom in scenario["deployment"]["domains"]:
            for z in dom.get("zones") or []:
                for nl in z.get("networkLocations") or []:
                    if nl["type"].startswith("POA"):
                        cfg = nl.get("poa5GConfig") or nl.get("poa4GConfig") or nl.get("poaWifiConfig") or {}
                        poas.append({"name": nl["name"], "zone": z["name"], "type": nl["type"],
                                     "cell": cfg.get("cellId") or cfg.get("macId") or nl["name"],
                                     "geo": nl.get("geoData") or {}})
                    for pl in nl.get("physicalLocations") or []:
                        if pl["type"] == "UE" and pl.get("geoData"):
                            ues.append(pl)
        first = ues[0]["geoData"]["location"]["coordinates"] if ues else [0.0, 0.0]
        self.frame = _Frame(*first)
        self.ues = {u["name"]: _Ue(u, self.frame) for u in ues}
        self.poas = []
        for p in poas:
            loc = (p["geo"].get("location") or {}).get("coordinates")
            if loc:
                p["xy"], p["radius"] = self.frame.xy(*loc), float(p["geo"].get("radius") or 1e9)
                self.poas.append(p)

    @classmethod
    def load(cls, path, **kw):
        return cls(yaml.safe_load(open(path)), **kw)

    def _now(self, t=None):
        t = (time.time() if t is None else t) - self.t0
        return math.floor(t / self.period) * self.period if self.period > 0 else t

    def attach(self, xy):
        best = None
        for p in self.poas:
            d = math.hypot(xy[0] - p["xy"][0], xy[1] - p["xy"][1])
            if d <= p["radius"] and (best is None or d < best[0]):
                best = (d, p)
        return best[1] if best else None

    def users(self, t=None):
        """address -> {lat, lon, accuracy, zone, poa, cell, ts}"""
        tq = self._now(t)
        out = {}
        for name, u in self.ues.items():
            x, y = u.pos(tq)
            if self.noise > 0:                     # same fix for every query within one period
                r = random.Random(zlib.crc32(f"{name}/{round(tq / max(self.period, 1e-3))}".encode()))
                x, y = x + r.gauss(0, self.noise), y + r.gauss(0, self.noise)
            lon, lat = self.frame.lonlat(x, y)
            p = self.attach((x, y))
            out[name] = {"lat": lat, "lon": lon, "accuracy": self.accuracy,
                         "zone": p["zone"] if p else None, "poa": p["name"] if p else None,
                         "cell": p["cell"] if p else None, "ts": self.t0 + tq}
        return out

    def cell_loads(self, t=None):
        """cellId -> PRB usage fields; load grows with the UEs attached (synthetic)."""
        n = {p["cell"]: 0 for p in self.poas}
        for u in self.users(t).values():
            if u["cell"] in n:
                n[u["cell"]] += 1
        return {c: {"dl_gbr_prb_usage_cell": 10 + 5 * k, "ul_gbr_prb_usage_cell": 5 + 3 * k,
                    "dl_nongbr_prb_usage_cell": 10 + 5 * k, "ul_nongbr_prb_usage_cell": 5 + 3 * k}
                for c, k in n.items()}

    def radio(self, t=None):
        """address -> {cellId: RSRP dBm} for every POA (log-distance path loss, deterministic): what a UE
        measures from its serving and neighbour cells (MEC 012 MeasRepUe)."""
        tq = self._now(t)
        out = {}
        for name, u in self.ues.items():
            x, y = u.pos(tq)
            out[name] = {p["cell"]: rsrp_dbm(math.hypot(x - p["xy"][0], y - p["xy"][1])) for p in self.poas}
        return out


def rsrp_dbm(d):
    """Indoor log-distance path loss for a small cell: -44 dBm at 1 m, exponent 3.5."""
    return round(-44.0 - 35.0 * math.log10(max(d, 1.0)), 1)


def rsrp_index(dbm):
    """3GPP TS 36.133 reporting range: 0 (< -140 dBm) .. 97 (>= -44 dBm)."""
    return max(0, min(97, int(math.floor(dbm + 141))))


def rsrq_index(serving_dbm, others_dbm):
    """RSRQ ~ serving / (serving + interference), reporting range 0 (-19.5 dB) .. 34 (-3 dB)."""
    lin = lambda v: 10 ** (v / 10)                                       # noqa: E731
    q = 10 * math.log10(lin(serving_dbm) / (lin(serving_dbm) + sum(lin(o) for o in others_dbm) + 1e-12)) - 3.0
    return max(0, min(34, int(round((q + 19.5) * 2))))

