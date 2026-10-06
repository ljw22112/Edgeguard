"""MEC-IPE stand-in: exposes MEC service data as oneM2M resources.

    python tools/mec_ipe.py --config config/site.yaml

In the oneM2M Hackathon's MEC Sandbox, a MEC Interworking Proxy Entity (MEC-IPE) writes UE
positions from the MEC Location API into the CSE, so oneM2M applications read MEC data as
ordinary resources.  The Sandbox's IPE (TR-0086) was not public yet when this was written,
so this script plays that role against any MEC 013 / 012 endpoint (the ETSI MEC Sandbox or
mec_mock) and keeps the layout configurable (mec_services.ipe in the config):

  <ipe.root>                       AE, e.g. MEC-IPE
    location/<ue>                  one container per UE (address with "." -> "_")
      contentInstance              MEC 013 UserInfo, as returned by queries/users
    rnis/<cell>                    one container per cell
      contentInstance              MEC 012 layer-2 cellInfo

A contentInstance is written only when the network reports a new fix (the Sandbox refreshes
UE positions about once a second), so the CSE load is one write per UE per update.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard import config                                    # noqa: E402
from edgeguard.mec_services import LocationClient, RnisClient   # noqa: E402
from edgeguard.onem2m import OneM2MClient                       # noqa: E402

log = logging.getLogger("mec-ipe")


def rn_of(address):
    return "ue_" + "".join(ch if ch.isalnum() else "_" for ch in str(address))


class Ipe:
    def __init__(self, cfg):
        ms, cse = cfg["mec_services"], cfg["cse"]
        ipe = ms.get("ipe") or {}
        self.root = ipe.get("root", "MEC-IPE")
        self.cse = OneM2MClient(cse["base_url"], cse["cse_rn"], ipe.get("origin", "SMecIpe"),
                                str(cse.get("rvi", "2a")), timeout=2.0)
        self.loc = LocationClient(ms["base_url"], ms.get("location_api", "location/v3"), frame=None)
        self.rnis = RnisClient(ms["base_url"], ms.get("rnis_api", "rni/v2"))
        self.poll_s, self.rnis_s = ipe.get("poll_s", 0.25), ipe.get("rnis_poll_s", 1.0)
        self.made, self.last = set(), {}
        self.stats = {"location_writes": 0, "rnis_writes": 0, "errors": 0}

    def setup(self):
        self.cse.create_ae(self.root, api="Nmec-ipe")
        for c in ("location", "rnis"):
            self.cse.with_retry(self.cse.create_container, self.root, c)

    def _container(self, group, rn):
        key = (group, rn)
        if key not in self.made:
            self.cse.with_retry(self.cse.create_container, f"{self.root}/{group}", rn, 10)
            self.made.add(key)
        return f"{self.root}/{group}/{rn}"

    def step_location(self):
        for u in self.loc.all_users():
            addr = u.get("address")
            ts = u.get("timestamp") or {}
            li = u.get("locationInfo") or {}
            key = (ts.get("seconds"), ts.get("nanoSeconds"), str(li.get("latitude")), str(li.get("longitude")))
            if addr is None or self.last.get(addr) == key:
                continue                                    # no new fix since the last write
            self.cse.create_cin(self._container("location", rn_of(addr)), u)
            self.last[addr] = key
            self.stats["location_writes"] += 1

    def step_rnis(self):
        for c in self.rnis.cells():
            cell = ((c.get("ecgi") or {}).get("cellId")) or c.get("cellId")
            if cell:
                self.cse.create_cin(self._container("rnis", f"cell_{cell}"), c)
                self.stats["rnis_writes"] += 1

    def run(self, duration=None):
        self.setup()
        t_end = None if duration is None else time.time() + duration
        last_rnis = 0.0
        while t_end is None or time.time() < t_end:
            t = time.time()
            try:
                self.step_location()
                if t - last_rnis >= self.rnis_s:
                    last_rnis = t
                    self.step_rnis()
            except Exception as e:                         # MEC or CSE hiccup: keep going
                self.stats["errors"] += 1
                log.warning("ipe step failed: %s", e)
                self.made.clear()                          # containers may have been reset
            time.sleep(max(0.0, self.poll_s - (time.time() - t)))
        return self.stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--duration", type=float, help="seconds (default: run forever)")
    a = ap.parse_args()
    stats = Ipe(config.load(a.config)).run(a.duration)
    print(stats)


if __name__ == "__main__":
    main()
