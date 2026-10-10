"""MCP server for ETSI MEC services: Location (MEC 013) and RNIS (MEC 012).

    python -m agent.mec_mcp --mec-url http://127.0.0.1:8085      # ETSI MEC Sandbox or mec_mock

Tools:
  ue_location      position of one UE (site frame and lat/lon) from the Location API
  all_ue_locations every UE the Location API reports
  cell_load        radio load per cell from RNIS (PRB usage, %)
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp.server.fastmcp import FastMCP                                 # noqa: E402

from edgeguard.mec_services import LocationClient, RnisClient, SiteFrame, cell_load_of, parse_user_info  # noqa: E402


def build(mec_url, location_api, rnis_api, lat0, lon0):
    frame = SiteFrame(lat0, lon0)
    loc = LocationClient(mec_url, api=location_api, frame=frame, timeout=3.0)
    rnis = RnisClient(mec_url, api=rnis_api, timeout=3.0)
    mcp = FastMCP("etsi-mec", log_level="WARNING")

    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)[:300]}

    @mcp.tool()
    def ue_location(address: str) -> dict:
        """Position of one UE (address, e.g. acr:10.100.0.1) from the MEC Location API."""
        return safe(lambda: loc.user(address) or {"error": "unknown UE"})

    @mcp.tool()
    def all_ue_locations() -> dict:
        """Every UE the MEC Location API reports, with its position in the site frame: {"ues": [...]}."""
        return safe(lambda: {"ues": [dict(parse_user_info(u, frame) or {}, address=u.get("address"))
                                     for u in loc.all_users()]})

    @mcp.tool()
    def cell_load(cell_id: str = "") -> dict:
        """Radio load per cell (RNIS layer-2 measurements, PRB usage %)."""
        return safe(lambda: {"cells": [{"cell_id": (c.get("ecgi") or {}).get("cellId") or c.get("cell_id"),
                                        "load_pct": cell_load_of(c)} for c in rnis.cells(cell_id or None)],
                             "max_load_pct": rnis.cell_load(cell_id or None)})

    return mcp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mec-url", default="http://127.0.0.1:8085")
    ap.add_argument("--location-api", default="location/v3")
    ap.add_argument("--rnis-api", default="rni/v2")
    ap.add_argument("--lat0", type=float, default=37.55)
    ap.add_argument("--lon0", type=float, default=127.07)
    a = ap.parse_args()
    build(a.mec_url, a.location_api, a.rnis_api, a.lat0, a.lon0).run("stdio")


if __name__ == "__main__":
    main()
