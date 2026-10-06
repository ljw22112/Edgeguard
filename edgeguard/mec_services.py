"""Clients for the ETSI MEC services EdgeGuard uses.

* Location API (ETSI GS MEC 013): `GET {root}/location/v3/queries/users?address=...`
  returns the network-derived position of a UE.  EdgeGuard uses it as a fallback
  measurement when a worker's UWB tag goes silent (radio shadow behind racks).
* Radio Network Information (ETSI GS MEC 012): `GET {root}/rni/v2/queries/layer2_meas`
  returns per-cell load.  When the cell serving the site is congested, alerts are
  given a larger time margin and refreshed more often.

Only the fields EdgeGuard reads are parsed, so the clients tolerate the
differences between API versions (v2 / v3) and the ETSI MEC Sandbox.
"""
from __future__ import annotations

import math

import requests

EARTH_R = 6378137.0


class SiteFrame:
    """WGS84 <-> local site metres (east = +x, north = +y) around an origin."""

    def __init__(self, lat0, lon0):
        self.lat0, self.lon0 = lat0, lon0
        self.k_lat = math.pi / 180 * EARTH_R
        self.k_lon = self.k_lat * math.cos(math.radians(lat0))

    def to_xy(self, lat, lon):
        return ((lon - self.lon0) * self.k_lon, (lat - self.lat0) * self.k_lat)

    def to_latlon(self, x, y):
        return (self.lat0 + y / self.k_lat, self.lon0 + x / self.k_lon)


class LocationClient:
    def __init__(self, base_url, api="location/v3", timeout=1.0, frame: SiteFrame | None = None):
        self.root = f"{base_url.rstrip('/')}/{api.strip('/')}"
        self.timeout = timeout
        self.frame = frame
        self.s = requests.Session()

    def user(self, address):
        """Return {"x", "y", "accuracy", "zone", "ts"} or None."""
        r = self.s.get(f"{self.root}/queries/users", params={"address": address}, timeout=self.timeout)
        if r.status_code != 200:
            return None
        users = (r.json().get("userList") or {}).get("user") or []
        if not users:
            return None
        u = users[0]
        li = u.get("locationInfo") or {}
        lat, lon = (li.get("latitude") or [None])[0], (li.get("longitude") or [None])[0]
        if lat is None or lon is None:
            return None
        x, y = self.frame.to_xy(lat, lon)
        ts = u.get("timestamp") or {}
        return {"x": x, "y": y, "accuracy": float(li.get("accuracy", 5.0)),
                "zone": u.get("zoneId"), "ts": ts.get("seconds", 0) + ts.get("nanoSeconds", 0) / 1e9}


class RnisClient:
    def __init__(self, base_url, api="rni/v2", timeout=1.0):
        self.root = f"{base_url.rstrip('/')}/{api.strip('/')}"
        self.timeout = timeout
        self.s = requests.Session()

    def cell_load(self, cell_id=None):
        """Highest downlink+uplink PRB usage (%) among the site's cells, or None."""
        params = {"cell_id": cell_id} if cell_id else None
        r = self.s.get(f"{self.root}/queries/layer2_meas", params=params, timeout=self.timeout)
        if r.status_code != 200:
            return None
        cells = r.json().get("cellInfo") or []
        best = None
        for c in cells:
            vals = [c.get(k) for k in ("dl_gbr_prb_usage_cell", "ul_gbr_prb_usage_cell",
                                        "dl_nongbr_prb_usage_cell", "ul_nongbr_prb_usage_cell")]
            vals = [v for v in vals if isinstance(v, (int, float))]
            if not vals:
                continue
            # GBR + non-GBR share the cell: their sum per direction is the load
            dl = (c.get("dl_gbr_prb_usage_cell") or 0) + (c.get("dl_nongbr_prb_usage_cell") or 0)
            ul = (c.get("ul_gbr_prb_usage_cell") or 0) + (c.get("ul_nongbr_prb_usage_cell") or 0)
            load = max(dl, ul)
            best = load if best is None else max(best, load)
        return best
